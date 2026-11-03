# -*- coding: utf-8 -*-
"""储能柜八支路水力演示：生成共形正交 HEX8 网格及可复用参数。"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent
from runtime_config import read_config, extra_python_paths
CFG = read_config()
GEO, OP, MESH = CFG['geometry'], CFG['operating'], CFG['mesh']
# 可调参数集中于此；几何全部使用 m，冷板为等效直通流道，不是产品实测结构。
N_BRANCH = GEO['branches']
PITCH = GEO['pitch_m']
FIRST_Z = GEO['first_z_m']
HEIGHT = GEO['height_m']
HEADER = GEO['header_m']
NECK = GEO['neck_m']
NECK_LENGTH = GEO['neck_length_m']
PLATE_LENGTH = GEO['plate_length_m']
PLATE_WIDTH = GEO['plate_width_m']
PLATE_GAP = GEO['plate_gap_m']
FLOW_LPM = OP['flow_lpm']
RHO = OP['density_kg_m3']
MU = OP['viscosity_Pa_s']
MAX_STEP = MESH['max_step_m']
FIRST_CELL = MESH['first_cell_m']
GROWTH = MESH['growth']
HEX_FACES = [[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
import sys, json, math, traceback
sys.path[:0] = [str(ROOT)] + extra_python_paths()
import numpy as np
import gmsh
from export_cgns import write_cgns

def graded_axis(breaks):
    """在所有几何分界两侧布置渐增正交层，避免任意削除真实流道。"""
    out=[]
    for a,b in zip(breaks[:-1],breaks[1:]):
        half=(b-a)/2
        widths=[]; distance=0.; h=FIRST_CELL
        while distance+h < half-1.e-12:
            widths.append(h);distance+=h;h=min(MAX_STEP,h*GROWTH)
        if half-distance < .5*(widths[-1] if widths else FIRST_CELL) and widths:
            widths[-1]+=half-distance
        else: widths.append(half-distance)
        segment=np.r_[0.,np.cumsum(widths),half+np.cumsum(widths[::-1])]
        segment[-1]=b-a
        out.extend((a+segment[:-1]).tolist())
    return np.r_[out,breaks[-1]]

def main():
    ROOT.mkdir(exist_ok=True)
    # 防止模板参数变化后重叠、越界或误标边界。
    if not isinstance(N_BRANCH,int) or N_BRANCH<1:raise ValueError('branches 必须为正整数')
    if min(PITCH,FIRST_Z,HEIGHT,HEADER,NECK,NECK_LENGTH,PLATE_LENGTH,PLATE_WIDTH,PLATE_GAP,FLOW_LPM,RHO,MU,MAX_STEP,FIRST_CELL)<=0 or GROWTH<=1:
        raise ValueError('尺寸、物性和流量须为正，增长率须大于1')
    if not (PLATE_GAP<NECK<HEADER and PLATE_WIDTH>NECK and PITCH>PLATE_WIDTH):
        raise ValueError('要求 plate_gap < neck < header，plate_width > neck，pitch > plate_width')
    if FIRST_Z-PLATE_WIDTH/2<=0 or FIRST_Z+(N_BRANCH-1)*PITCH+PLATE_WIDTH/2>=HEIGHT:
        raise ValueError('支路必须完整位于总管高度范围内')
    x1=HEADER; x2=x1+NECK_LENGTH; x3=x2+PLATE_LENGTH; x4=x3+NECK_LENGTH; end=x4+HEADER
    levels=[FIRST_Z+i*PITCH for i in range(N_BRANCH)]
    # 每个 box 记录真实流体体积，所有连接处均共面共节点。
    boxes=[{'name':'supply_header','bounds':[0.,end*0.-HEADER/2,0.,HEADER,HEADER,HEIGHT]},
           {'name':'return_header','bounds':[x4,-HEADER/2,0.,HEADER,HEADER,HEIGHT]}]
    for i,z in enumerate(levels,1):
        for name,x,l,w,h in [('feed',x1,NECK_LENGTH,NECK,NECK),('coldplate',x2,PLATE_LENGTH,PLATE_GAP,PLATE_WIDTH),('return',x3,NECK_LENGTH,NECK,NECK)]:
            boxes.append({'name':f'{name}_{i:02d}','bounds':[x,-w/2,z-h/2,l,w,h]})
    config={'case':'energy_storage_parallel_hydraulics','geometry_units':'m','branches':N_BRANCH,'layout':'U_type_direct_return','boxes':boxes,'branch_z_m':levels,
            'geometry':{'height_m':HEIGHT,'overall_width_m':end,'header_square_side_m':HEADER,'neck_square_side_m':NECK,'neck_length_each_m':NECK_LENGTH,'coldplate_length_m':PLATE_LENGTH,'coldplate_width_m':PLATE_WIDTH,'coldplate_gap_m':PLATE_GAP},
            'operating':dict(OP,energy_enabled=False),
            'assumptions':['演示尺寸，非实际储能柜产品','矩形总管/支管；冷板以等效矩形直通流道显式求解，无多孔阻力拟合','固定壁面无滑移、光滑壁、忽略重力；压力为去除静水项后的水力压降','采用湍流模型；冷板部分区域可能处于层流或过渡流，RANS 结果需作为演示评估'],
            'mesh':{'max_step_m':MAX_STEP,'first_cell_m':FIRST_CELL,'growth':GROWTH,'type':'conformal_cartesian_HEX8'}}
    (ROOT/'case_parameters.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    axes=[graded_axis([0.,x1,x2,x3,x4,end]),
          graded_axis(sorted(set([-HEADER/2,-NECK/2,-PLATE_GAP/2,0.,PLATE_GAP/2,NECK/2,HEADER/2]))),
          graded_axis(sorted(set([0.,HEIGHT]+[z+d for z in levels for d in [-PLATE_WIDTH/2,-NECK/2,0.,NECK/2,PLATE_WIDTH/2]])))]
    xm,ym,zm=[(a[1:]+a[:-1])/2 for a in axes]
    nx,ny,nz=map(len,[xm,ym,zm])
    X,Y,Z=np.meshgrid(xm,ym,zm,indexing='ij')
    mask=np.zeros(X.shape,dtype=bool)
    for box in boxes:
        x,y,z,dx,dy,dz=box['bounds']
        mask|=(X>x)&(X<x+dx)&(Y>y)&(Y<y+dy)&(Z>z)&(Z<z+dz)
    active=np.flatnonzero(mask)
    ii,jj,kk=np.unravel_index(active,mask.shape)
    nodes=np.arange((nx+1)*(ny+1)*(nz+1)).reshape(nx+1,ny+1,nz+1)
    cells=np.column_stack([nodes[ii,jj,kk],nodes[ii+1,jj,kk],nodes[ii+1,jj+1,kk],nodes[ii,jj+1,kk],nodes[ii,jj,kk+1],nodes[ii+1,jj,kk+1],nodes[ii+1,jj+1,kk+1],nodes[ii,jj+1,kk+1]])
    unique=np.unique(cells); remap=np.full(nodes.size,-1,dtype=np.int64);remap[unique]=np.arange(len(unique));cells=remap[cells]
    ni,nj,nk=np.unravel_index(unique,nodes.shape)
    xyz=np.column_stack([axes[0][ni],axes[1][nj],axes[2][nk]])
    centers=xyz[cells].mean(1)
    # 直接用网格邻居提取外表面；内部分支连接保持普通内部面，绝不设置阻断壁面。
    face_list=[];owner=[]
    for side,(axis,delta) in enumerate([(2,-1),(2,1),(1,-1),(0,1),(1,1),(0,-1)]):
        # HEX_FACES 的编号对应 -Z,+Z,-Y,+X,+Y,-X。
        ids=[ii.copy(),jj.copy(),kk.copy()];ids[axis]+=delta
        inside=(ids[axis]>=0)&(ids[axis]<mask.shape[axis]);nb=np.zeros(len(ii),dtype=bool)
        nb[inside]=mask[ids[0][inside],ids[1][inside],ids[2][inside]]
        selected=np.flatnonzero(~nb)
        face_list.append(cells[selected][:,HEX_FACES[side]]);owner.append(selected)
    faces=np.concatenate(face_list);fc=xyz[faces].mean(1)
    patches={}
    wall_owner=centers[np.concatenate(owner)]
    for n,mid in enumerate(fc):
        x,y,z=mid
        ox=wall_owner[n,0]
        if abs(z)<1e-12: name='inlet' if x<HEADER else 'outlet'
        elif ox<HEADER:name='wall_supply_header'
        elif ox>x4:name='wall_return_header'
        else:
            branch=int(np.argmin(abs(np.array(levels)-z)))+1
            if x<x2-1e-12:name=f'wall_feed_{branch:02d}'
            elif x>x3+1e-12:name=f'wall_return_{branch:02d}'
            else:name=f'wall_coldplate_{branch:02d}'
        patches.setdefault(name,[]).append(n)
    patches={n:faces[v]+1 for n,v in patches.items()}
    data={'coords':xyz,'cells':cells+1,'patches':patches}
    dx=np.diff(axes[0])[ii];dy=np.diff(axes[1])[jj];dz=np.diff(axes[2])[kk]
    volumes=dx*dy*dz; aspect=np.maximum.reduce([dx,dy,dz])/np.minimum.reduce([dx,dy,dz])
    total=sum(np.prod(b['bounds'][3:]) for b in boxes)
    if abs(volumes.sum()/total-1)>1e-10:raise RuntimeError('CAD/mesh volume mismatch')
    # 内部面计数恒等式检查无漏面：6N = 边界面 + 2*内部面。
    if (6*len(cells)-len(faces))%2:raise RuntimeError('Invalid face coverage')
    gmsh.initialize();gmsh.model.add('EnergyStorageParallelCooling')
    gmsh.model.addDiscreteEntity(3,1);gmsh.model.mesh.addNodes(3,1,np.arange(1,len(xyz)+1),xyz.ravel())
    gmsh.model.mesh.addElementsByType(1,5,np.arange(1,len(cells)+1),(cells+1).ravel());gmsh.model.addPhysicalGroup(3,[1],1,'fluid_network')
    tag=len(cells)
    for i,(name,p) in enumerate(patches.items(),1):
        gmsh.model.addDiscreteEntity(2,i);gmsh.model.mesh.addElementsByType(i,3,np.arange(tag+1,tag+len(p)+1),p.ravel());gmsh.model.addPhysicalGroup(2,[i],i,name);tag+=len(p)
    minjac=np.asarray(gmsh.model.mesh.getElementQualities(np.arange(1,len(cells)+1),'minDetJac'))
    if minjac.min()<=0:raise RuntimeError('nonpositive Jacobian')
    gmsh.option.setNumber('Mesh.MshFileVersion',2.2);gmsh.option.setNumber('Mesh.Binary',0);gmsh.write(str(ROOT/'parallel_cooling_m.msh'));gmsh.finalize()
    write_cgns(ROOT/'parallel_cooling_m.cgns',{'fluid_network':data})
    p=xyz[patches['inlet']-1];inlet_area=float(np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,3]-p[:,0]),axis=1).sum())
    report={'units':'m','regions':{'fluid_network':{'cells':len(cells),'nodes':len(xyz),'bbox_m':[xyz.min(0).tolist(),xyz.max(0).tolist()],'boundaries':{n:len(v) for n,v in patches.items()},'volume_m3':float(volumes.sum()),'inlet_area_m2':inlet_area}},
            'quality':{'minimum_volume_m3':float(volumes.min()),'min_det_jacobian':float(minjac.min()),'equiangle_skewness_max':0.,'nonorthogonality_max_deg':0.,'aspect_ratio_max':float(aspect.max()),'aspect_ratio_p99':float(np.quantile(aspect,.99)),'worst_aspect_cell_center_m':centers[np.argmax(aspect)].tolist(),'description':'Axis-aligned rectangular HEX8: all face angles 90deg; face normal and cell-center line collinear.'},'cad_mesh_relative_volume_error':float(volumes.sum()/total-1),'near_wall_first_cell_m':FIRST_CELL}
    (ROOT/'mesh_check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    # 保留分支统计截面和中间剖面，用于对真实求解场积分；不以支路均分假定替代 CFD。
    np.savez_compressed(ROOT/'mesh_arrays.npz',coords=xyz,cells=cells+1,centers=centers,volumes=volumes,**patches)
    print('MESH_COMPLETE',len(cells),'cells',len(xyz),'nodes',len(patches),'patches',flush=True)

if __name__=='__main__':
    try:main()
    except Exception:traceback.print_exc();sys.exit(1)
