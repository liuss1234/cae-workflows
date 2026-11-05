# -*- coding: utf-8 -*-
"""无商业软件的迁移/负向测试；所有产物位于临时目录。"""
import copy
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from fan_case import SKILL,CONFIG_REL,TOP_DIRS,initialize,read_json,write_json,validate_config,pack,verify,safe_file,run_manifest
from analyze_history import analyze
from render_star_macro import render
from make_qflux_config import make
from fan_case import digest


class WorkflowTest(unittest.TestCase):
    """检查观察到的工况、失败阻断和包完整性，不匹配固定文案。"""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='fan transfer 中文 ')
        self.root=Path(self.temp.name);self.source=self.root/'原始 STEP.step';self.source.write_text('synthetic source fixture',encoding='utf8')
        self.case=self.root/'新案例 with spaces';initialize(self.case,self.source)
        self.cfg=read_json(self.case/CONFIG_REL)
        self.cfg['operating'].update(rpm=180,direction_viewed_from_plus_z='clockwise')
        self.cfg['geometry']['swept_diameter_m']=1.2
        self.cfg['acceptance']['blade_full_layer_min_fraction']=.9928
        write_json(self.case/CONFIG_REL,self.cfg)

    def tearDown(self):self.temp.cleanup()

    def test_three_directories_and_no_overwrite(self):
        self.assertEqual(set(p.name for p in self.case.iterdir()),set(TOP_DIRS))
        with self.assertRaises(FileExistsError):initialize(self.case,self.source)

    def test_rotation_measurement_and_layer_height(self):
        d=validate_config(self.cfg)
        self.assertAlmostEqual(d['omega_vector_rad_s'][2],-6*math.pi)
        self.assertAlmostEqual(d['measurement_diameter_m'],2.)
        h=d['first_layer_theoretical_m'];self.assertAlmostEqual(sum(h*1.2**i for i in range(5)),.0012)
        self.cfg['operating']['direction_viewed_from_plus_z']='counterclockwise'
        self.assertGreater(validate_config(self.cfg)['omega_vector_rad_s'][2],0)

    def test_unknown_conditions_units_and_coverage_block(self):
        for group,key,value in [('operating','rpm',None),('operating','rpm',float('nan')),('operating','direction_viewed_from_plus_z','unknown'),('units','mesh','mm'),('acceptance','blade_full_layer_min_fraction',None),('geometry','swept_diameter_m',12.)]:
            with self.subTest(key=key,value=value):
                cfg=copy.deepcopy(self.cfg);cfg[group][key]=value
                with self.assertRaises(ValueError):validate_config(cfg)

    def test_macro_uses_case_paths_and_nondefault_parameters(self):
        self.cfg['mesh'].update(blade_layers=7,blade_size_m=.0025);write_json(self.case/CONFIG_REL,self.cfg)
        out=self.root/'宏 脚本/MeshCeilingFan.java';render(self.case,self.root/'mesh',self.root/'logs',out)
        text=out.read_text(encoding='ascii')
        self.assertIn('setNumLayers(7)',text);self.assertIn('setAbsoluteSize(0.0025,m)',text)
        self.assertNotIn('@@',text)
        with self.assertRaises(FileExistsError):render(self.case,self.root/'mesh',self.root/'logs',out)

    def test_stability_unstable_and_near_zero(self):
        history=self.root/'monitor.dat'
        history.write_text('# iteration Q\n'+''.join('%d %.10g\n'%(i,1+i*1e-7) for i in range(1,301)))
        self.assertTrue(analyze(history,1,200,1.,1e-6,300)['plateau_passed'])
        history.write_text(''.join('%d %g\n'%(i,i*.01) for i in range(1,301)))
        self.assertFalse(analyze(history,1,200,1.,1e-6)['plateau_passed'])
        history.write_text(''.join('%d %g\n'%(i,1e-9*(-1)**i) for i in range(1,301)))
        result=analyze(history,1,200,1.,1e-6)
        self.assertFalse(result['plateau_passed']);self.assertIsNone(result['relative_span_percent'])

    def test_history_missing_duplicate_short_nan_fail(self):
        history=self.root/'bad.dat'
        for text in ['1 1\n3 1\n','1 1\n1 1\n','1 1\n','1 nan\n2 1\n']:
            history.write_text(text)
            with self.assertRaises(ValueError):analyze(history,1,2,1.,1e-6)

    def test_archive_roundtrip_and_tampering(self):
        name='01模型文件/01原始模型/'+self.source.name
        manifest=self.root/'delivery.json';write_json(manifest,{'files':[name,str(CONFIG_REL.as_posix())]})
        archive=self.root/'delivery.zip';pack(self.case,manifest,archive)
        self.assertEqual(verify(archive)['files'],2)
        bad=self.root/'tampered.zip'
        with zipfile.ZipFile(archive) as src,zipfile.ZipFile(bad,'w') as dst:
            for n in src.namelist():dst.writestr(n,b'changed' if n==name else src.read(n))
        with self.assertRaises(ValueError):verify(bad)
        with self.assertRaises(FileExistsError):pack(self.case,manifest,archive)

    def test_path_escape_and_private_files(self):
        for name in ['../outside','/absolute/file','C:/private','01模型文件/../x','01模型文件\\x']:
            with self.assertRaises(ValueError):safe_file(self.case,name)
        secret=self.case/'03日志脚本/environment.json';secret.write_text('{}')
        with self.assertRaises(ValueError):safe_file(self.case,secret.relative_to(self.case).as_posix())

    def test_command_plan_does_not_execute(self):
        plan=self.root/'plan.json';write_json(plan,dict(cwd=str(self.root),commands=[['no-such-executable']],log=str(self.root/'not-created.log')))
        self.assertFalse(run_manifest(plan,False)['executed']);self.assertFalse((self.root/'not-created.log').exists())

    def test_qflux_configuration_tracks_measurement_and_mesh(self):
        """改变检测面时名称、说明与几何同步；过期网格证据必须阻断。"""
        self.cfg['measurement'].update(height_above_floor_m=1.3,diameter_offset_m=.5)
        self.cfg['solver']['run_full_iterations']=True
        write_json(self.case/CONFIG_REL,self.cfg)
        mesh=self.root/'mesh.cgns';mesh.write_bytes(b'synthetic mesh hash fixture')
        quality=self.root/'quality.json'
        record=dict(passed=True,mesh_sha256=digest(mesh),cells_total=5,zones={
            'fluid_stationary_surfaces_m':dict(cells=3,boundaries=['if_rotor_stat','wall_floor']),
            'fluid_rotating_surfaces_m':dict(cells=2,boundaries=['if_rotor_rot','wall_blades','wall_hub'])})
        write_json(quality,record)
        out=make(self.case,quality,mesh,self.root/'new.qfx',self.root/'result',self.root/'setup.json')
        self.assertEqual(out['measurement']['center_m'],[0.,0.,1.3])
        self.assertAlmostEqual(out['measurement']['diameter_m'],1.7)
        self.assertEqual(out['measurement']['height_above_floor_m'],1.3)
        self.assertEqual(out['measurement']['diameter_offset_m'],.5)
        self.assertAlmostEqual(out['physics']['omega_rad_s'],-6*math.pi)
        self.assertTrue(out['solver']['run_full_iterations'])
        mesh.write_bytes(b'changed mesh')
        with self.assertRaises(ValueError):
            make(self.case,quality,mesh,self.root/'new.qfx',self.root/'result',self.root/'setup2.json')


if __name__=='__main__':unittest.main(verbosity=2)
