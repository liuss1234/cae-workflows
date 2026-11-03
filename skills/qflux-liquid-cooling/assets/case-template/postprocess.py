# -*- coding: utf-8 -*-
"""读取真实 QFlux 结果，积分八支路流量并生成水力性能图表。"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent
from runtime_config import read_config, extra_python_paths
CFG = read_config()
RUN_NAME = 'run'                 # 可改为已完成的续算结果目录。
OUTPUT_NAME = 'results_summary'
GEO = CFG['geometry']
SECTIONS_M = [GEO['header_m']+GEO['neck_length_m']+f*GEO['plate_length_m'] for f in CFG['post']['section_fractions']]
COORD_TOL = 1.e-6                # QFlux ASCII 坐标舍入容差，单位 m。
HEX_FACES = [[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
MASS_LIMIT_PERCENT = CFG['validation']['mass_limit_percent']
PRESSURE_SPAN_LIMIT_PERCENT = CFG['validation']['pressure_span_limit_percent']
RESIDUAL_LIMIT = CFG['solver']['residual_limit']
import json, csv, sys, xml.etree.ElementTree as ET
sys.path[:0] = extra_python_paths()
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.font_manager import fontManager, FontProperties
font = Path(CFG['post']['font_path']) if CFG['post']['font_path'] else Path('/__unset_font__')
if font.exists():
    fontManager.addfont(str(font)); plt.rcParams['font.family'] = FontProperties(fname=str(font)).get_name()
plt.rcParams['axes.unicode_minus'] = False


def monitor(path, fields):
    """按实际标题选择列，兼容续算标题重现；拒绝缺列及非有限值。"""
    rows, selected, header = [], None, None
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        p = line.split()
        if not p: continue
        if p[0] == '#iter':
            header = ['iter'] + p[1:]
            selected = [header.index(f) for f in ['iter'] + fields]
            continue
        try: values = list(map(float, p))
        except ValueError: continue
        if selected is None or len(values) != len(header): raise ValueError('监测标题不匹配：'+str(path))
        rows.append([values[j] for j in selected])
    data = np.asarray(rows)
    if not data.size or not np.isfinite(data).all(): raise ValueError('无有效监测数据：'+str(path))
    return data


def read_vtu(path):
    """读取官方 ASCII VTU；保留连接关系以验证节点和单元顺序。"""
    result = {'point':{}, 'cell':{}, 'topology':{}}
    stack = []
    for event, element in ET.iterparse(path, events=['start','end']):
        if event == 'start': stack.append(element.tag); continue
        if element.tag == 'DataArray':
            parent = stack[-2]
            if element.get('format') != 'ascii': raise ValueError('VTK 不是 ASCII')
            n = int(element.get('NumberOfComponents','1'))
            values = np.fromstring(element.text or '', sep=' ')
            if n > 1: values = values.reshape(-1,n)
            if parent == 'Points': result['coords'] = values
            elif parent in ['PointData','CellData','Cells']:
                key = {'PointData':'point','CellData':'cell','Cells':'topology'}[parent]
                result[key][element.get('Name')] = values
            element.clear()
        stack.pop()
    return result


def section_integrals(coords, cells, field, config):
    """按相邻单元中心线性插值 Ux 到内部面并积分，避免节点壁面外推误差。

    这属于结果场重构积分，不等同于求解器压力修正后的守恒面通量。
    同时保留三个轴向截面，量化重构积分误差。
    """
    cc = coords[cells].mean(1)
    centers = np.asarray(config['branch_z_m'])
    values, actual_x = [], []
    xp = np.unique(coords[:,0])
    for target in SECTIONS_M:
        x = xp[np.argmin(abs(xp-target))]; actual_x.append(float(x))
        # 仅保留 +X 面，其相邻的 -X 面用于建立面两侧单元对应关系。
        left_ids = np.flatnonzero(np.all(abs(coords[cells[:,[1,2,6,5]],0]-x)<1.e-10,axis=1))
        right_ids = np.flatnonzero(np.all(abs(coords[cells[:,[0,3,7,4]],0]-x)<1.e-10,axis=1))
        lf = cells[left_ids][:,[1,2,6,5]]; rf = cells[right_ids][:,[0,3,7,4]]
        lookup = {tuple(sorted(f)):int(i) for f,i in zip(rf,right_ids)}
        right = np.asarray([lookup[tuple(sorted(f))] for f in lf])
        face_xyz = coords[lf]; mid = face_xyz.mean(1)
        area = np.ptp(face_xyz[:,:,1],axis=1)*np.ptp(face_xyz[:,:,2],axis=1)
        dl = x-cc[left_ids,0]; dr=cc[right,0]-x
        ux = (field[left_ids]*dr+field[right]*dl)/(dl+dr)
        ids = np.argmin(abs(mid[:,2,None]-centers[None,:]),axis=1)
        flow = np.bincount(ids,weights=ux*area,minlength=len(centers))
        areas = np.bincount(ids,weights=area,minlength=len(centers))
        expected=config['geometry']['coldplate_gap_m']*config['geometry']['coldplate_width_m']
        if not np.allclose(areas,expected,rtol=1.e-8): raise ValueError('截面积与几何不匹配')
        values.append(flow)
    return np.asarray(values),actual_x


def plot_field(ax, coords, faces, values, title, unit, cmap):
    """只绘制实际流体剖面，保留八支路之间的实体空隙。"""
    poly = PolyCollection(coords[faces][:,:,[0,2]],array=values[faces].mean(1),cmap=cmap,
                          linewidths=0,edgecolors='none',rasterized=True)
    ax.add_collection(poly); ax.autoscale_view(); ax.set_aspect('equal')
    ax.set_title(title); ax.set_xlabel('X / m'); ax.set_ylabel('Z / m')
    for i in range(GEO['branches']):
        z=GEO['first_z_m']+i*GEO['pitch_m']
        ax.text(GEO['header_m']+GEO['neck_length_m']+GEO['plate_length_m']/2,z+GEO['plate_width_m']*.75,f'{i+1:02d}',ha='center',fontsize=8)
    cb=plt.colorbar(poly,ax=ax,pad=.025,fraction=.045);cb.set_label(unit)
    inlet_x=GEO['header_m']/2
    outlet_x=GEO['header_m']*1.5+2*GEO['neck_length_m']+GEO['plate_length_m']
    offset=GEO['height_m']*.06
    ax.annotate('入口',(inlet_x,0),(inlet_x,-offset),ha='center',arrowprops={'arrowstyle':'->'})
    ax.annotate('',(outlet_x,-offset*.55),(outlet_x,0),arrowprops={'arrowstyle':'->'})
    ax.text(outlet_x,-offset,'出口',ha='center',va='top')


def main():
    run=ROOT/(sys.argv[1] if len(sys.argv)>1 else RUN_NAME)
    finished=json.loads((run/'finished.json').read_text(encoding='utf-8-sig'))
    if finished['exitCode']!=0:raise ValueError('求解未正常结束')
    if len(SECTIONS_M)!=3 or not all(0<f<1 for f in CFG['post']['section_fractions']):raise ValueError('需三个冷板内部截面')
    readback=json.loads((ROOT/'post'/'result_readback.json').read_text(encoding='utf-8'))
    check=json.loads((ROOT/'readback_check.json').read_text(encoding='utf-8'))
    if not check['passed'] or not check.get('source_data'):raise ValueError('最终场尚未独立回读')
    if Path(check['source_qfx']).resolve()!=Path(readback['source_qfx']).resolve() or (ROOT/check['source_data']).resolve()!=Path(readback['source_data']).resolve():
        raise ValueError('独立回读与官方导出的 QFX/DAT 配对不一致')
    source_iteration=int(Path(readback['source_data']).stem.rsplit('-',1)[1])
    output=ROOT/OUTPUT_NAME;output.mkdir(exist_ok=True)
    config=json.loads((ROOT/'case_parameters.json').read_text(encoding='utf-8'))
    files=list((ROOT/'post').rglob('fluid_network.vtu'))
    if len(files)!=1:raise ValueError('应只有一个官方导出 VTU')
    vtk=read_vtu(files[0]);mesh=np.load(ROOT/'mesh_arrays.npz')
    coords=mesh['coords'];cells=mesh['cells'].astype(np.int64)-1
    error=float(np.max(abs(coords-vtk['coords'])))
    if error>COORD_TOL:raise ValueError('VTK 节点顺序不匹配')
    top=vtk['topology']; exported=top['connectivity'].astype(np.int64)
    if not np.all(top['types']==12) or not np.array_equal(np.sort(exported.reshape(-1,8),axis=1),np.sort(cells,axis=1)):
        raise ValueError('VTK 单元顺序/连接关系不匹配')
    for key in ['Velocity-X','Pressure']:
        if len(vtk['cell'][key])!=len(cells) or not np.isfinite(vtk['cell'][key]).all(): raise ValueError('结果场无效')
    q,xs=section_integrals(coords,cells,vtk['cell']['Velocity-X'],config)
    q_lpm=q*60000;mid=q_lpm[1];mean=float(mid.mean());dev=(mid/mean-1)*100
    rho=config['operating']['density_kg_m3'];mu=config['operating']['viscosity_Pa_s']
    with (output/'branch_flow.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['支路编号_从下至上','Z_m','流量_L_min','质量流量_kg_s','占总重构流量_%','相对支路均值偏差_%','支管平均速度_m_s','支管Re','冷板Re','三截面流量极差_L_min'])
        for i,v in enumerate(mid):
            neck=GEO['neck_m'];width=GEO['plate_width_m'];gap=GEO['plate_gap_m']
            qq=v/60000;un=qq/neck**2;up=qq/(width*gap);dh=2*width*gap/(width+gap)
            writer.writerow([f'{i+1:02d}',config['branch_z_m'][i],v,qq*rho,v/mid.sum()*100,dev[i],un,rho*un*neck/mu,rho*up*dh/mu,np.ptp(q_lpm[:,i])])
    pressure_i=monitor(run/'coolant-pressure_inlet.dat',['p']);pressure_o=monitor(run/'coolant-pressure_outlet.dat',['p'])
    mi=monitor(run/'coolant-mass_inlet.dat',['massFlowRate']);mo=monitor(run/'coolant-mass_outlet.dat',['massFlowRate'])
    residual_fields=['continuity','U.x','U.y','U.z','omega','k'];res=monitor(run/'coolant-Residual.dat',residual_fields)
    # QSolver 收敛退出时，DAT 文件编号可为最后监测编号加一；仅接受日志确认的这一例外。
    monitor_iteration=int(res[-1,0])
    if source_iteration!=monitor_iteration:
        log=run/'solver_stdout.log'
        log_text=log.read_text(encoding='utf-8',errors='replace') if log.exists() else ''
        if not (source_iteration==monitor_iteration+1 and 'Convergent: Residual' in log_text and Path(readback['source_data']).name in log_text and 'solver finished, code = 0' in log_text):
            raise ValueError('场文件与监测最后迭代不一致，拒绝混用不同阶段结果')
    if len(res)<200:raise ValueError('至少需要200次监测数据评估稳定性')
    if not mi[-1,1]<0<mo[-1,1]:raise ValueError('进出口方向不正确')
    if not np.array_equal(pressure_i[:,0],pressure_o[:,0]):raise ValueError('进出口压力监测迭代不一致')
    if mi[-1,0]!=mo[-1,0] or mi[-1,0] not in [monitor_iteration,source_iteration]:raise ValueError('边界通量与最终场阶段不一致')
    dp=pressure_i[:,1]-pressure_o[:,1];drop=float(dp[-1]);mass_error=abs(mi[-1,1]+mo[-1,1])/abs(mi[-1,1])*100
    span=float(np.ptp(dp[-200:])/abs(drop)*100)
    converged=bool(np.max(res[-1,1:])<=RESIDUAL_LIMIT and mass_error<=MASS_LIMIT_PERCENT and span<=PRESSURE_SPAN_LIMIT_PERCENT)
    flow=config['operating']['flow_lpm']
    settings=json.loads((ROOT/'readback_settings.json').read_text(encoding='utf-8-sig'))
    scheme_enum=settings['region'][0]['numericMethod']['discreteAlgorithm']['spatial']['momentum']['convection']
    scheme_label={1:'一阶迎风',2:'二阶迎风'}.get(scheme_enum,'格式待核验')
    data={'iteration':int(res[-1,0]),'data_filename_iteration':source_iteration,'run_directory':str(run),'source_qfx':readback['source_qfx'],'source_data':readback['source_data'],'momentum_scheme':scheme_label,'momentum_scheme_enum':scheme_enum,'pressure_drop_Pa':drop,'hydraulic_resistance_Pa_s_m3':drop/(flow/60000),'pressure_drop_Pa_per_L_min':drop/flow,'pump_hydraulic_power_W':drop*flow/60000,
          'mass_inlet_kg_s':float(mi[-1,1]),'mass_outlet_kg_s':float(mo[-1,1]),'mass_imbalance_percent':float(mass_error),
          'outlet_flow_L_min':float(mo[-1,1]/rho*60000),'branch_flow_L_min':mid.tolist(),'branch_mean_L_min':mean,'branch_CV_percent':float(np.std(mid)/mean*100),
          'branch_spread_percent':float(np.ptp(mid)/mean*100),'branch_max_deviation_percent':float(abs(dev).max()),'branch_max_min_ratio':float(mid.max()/mid.min()),
          'integration_x_m':xs,'all_section_flow_L_min':q_lpm.tolist(),'section_sum_L_min':q_lpm.sum(1).tolist(),
          'reconstructed_sum_error_vs_inlet_percent':float((mid.sum()/(-mi[-1,1]/rho*60000)-1)*100),
          'last_200_pressure_span_percent':span,'residuals':dict(zip(residual_fields,map(float,res[-1,1:]))),'convergence_checks_passed':converged,
          'coordinate_mapping_max_error_m':error,'cell_connectivity_verified':True,'mesh_convergence_study_performed':False}
    if 'yPlus' in vtk['cell']:data['y_plus_cell_range']=[float(vtk['cell']['yPlus'].min()),float(vtk['cell']['yPlus'].max())]
    (output/'simulation_summary.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    faces=cells[:,HEX_FACES].reshape(-1,4);faces=faces[np.all(abs(coords[faces,1])<1.e-12,axis=1)]
    _,ids=np.unique(np.sort(faces,axis=1),axis=0,return_index=True);faces=faces[ids]
    speed=np.sqrt(sum(vtk['point'][n]**2 for n in ['Velocity-X','Velocity-Y','Velocity-Z']))
    fig,axes=plt.subplots(1,2,figsize=(11,9))
    plot_field(axes[0],coords,faces,speed,'流速云图 · Y=0','速度 / (m/s)','viridis')
    plot_field(axes[1],coords,faces,vtk['point']['Pressure'],'静压云图 · Y=0','表压 / Pa','cividis')
    status=scheme_label+' · '+('收敛检查通过' if converged else '阶段结果：尚未达到全部收敛阈值')
    fig.suptitle(f'储能柜 {GEO["branches"]} 支路并联液冷管路 · QFlux\n'+status,fontsize=14)
    fig.text(.5,.035,f'{config["operating"]["temperature_C"]:g}°C 清水 · {flow:g} L/min · 等温 · 无重力 | Δp={drop:.2f} Pa | 流量 CV={data["branch_CV_percent"]:.2f}%',ha='center')
    fig.tight_layout(rect=[0,.06,1,.96]);fig.savefig(output/'cfd_fields.png',dpi=180);plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,4.8));bars=ax.bar(np.arange(1,GEO['branches']+1),mid,color='#217aa3');ax.axhline(flow/GEO['branches'],color='#b24d37',ls='--',label=f'理想均流 {flow/GEO["branches"]:g} L/min')
    ax.bar_label(bars,fmt='%.4f',padding=3);ax.set_xlabel('支路编号（从下至上）');ax.set_ylabel('流量 / (L/min)');ax.legend();ax.set_ylim(0,max(mid)*1.18)
    ax.set_title('各支路流量：冷板中截面速度场积分\n'+status);fig.tight_layout();fig.savefig(output/'branch_flow.png',dpi=180);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4.3))
    for j,n in enumerate(residual_fields,1):axes[0].semilogy(res[:,0],res[:,j],label=n)
    axes[0].axhline(RESIDUAL_LIMIT,color='gray',ls='--');axes[0].legend(fontsize=8);axes[0].set_ylabel('残差');axes[0].set_title('本求解阶段残差')
    axes[1].plot(pressure_i[:,0],dp);axes[1].set_ylabel('进出口压降 / Pa');axes[1].set_title('压降监测')
    for ax in axes:ax.set_xlabel('迭代次数');ax.grid(alpha=.25)
    fig.tight_layout();fig.savefig(output/'convergence.png',dpi=180);plt.close(fig)
    print(json.dumps(data,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
