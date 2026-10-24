#!/usr/bin/env python3
"""Function-stage room geometry and engineering evidence, not a runtime export.

Run: blender -b --python scripts/build_room3d_review.py -- --output rooms/club-room-3d
Only procedural review geometry is authored. No avatars or final asset meshes are
created. Original app artwork and source remain untouched.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    opts = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    output = opts.output.resolve()
    for part in ('plans', 'renders'):
        (output/part).mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system='METRIC'
    scene.unit_settings.scale_length=1.0
    scene.render.engine='BLENDER_WORKBENCH'
    scene.render.image_settings.file_format='PNG'
    scene.render.image_settings.color_mode='RGBA'
    scene.render.resolution_percentage=100
    scene.render.film_transparent=False
    scene.world.color=(1,1,1)
    scene.view_settings.view_transform='Standard'
    shade=scene.display.shading
    shade.light='STUDIO';shade.color_type='MATERIAL'
    shade.show_shadows=True;shade.show_cavity=True;shade.cavity_type='BOTH'
    shade.curvature_ridge_factor=1.5;shade.curvature_valley_factor=1.5
    shade.show_object_outline=True;shade.object_outline_color=(.045,.045,.045)
    shade.background_type='WORLD';shade.show_specular_highlight=False
    materials={}
    for name,tone in [('shell',.78),('floor',.89),('sofa',.32),('seat',.43),('table',.48),('wood',.52),('paper',.94),('detail',.22),('glass',.92),('metal',.36)]:
        mat=bpy.data.materials.new(name);mat.diffuse_color=(tone,tone,tone,1);materials[name]=mat
    all_objects=[];openings=[]
    def box(name,loc,dims,material='shell',bevel=0,layer='lower',role=''):
        bpy.ops.mesh.primitive_cube_add(size=1,location=loc)
        obj=bpy.context.object;obj.name=name;obj.dimensions=dims
        bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
        obj.data.materials.append(materials[material])
        if bevel:
            mod=obj.modifiers.new('soft_edges','BEVEL');mod.width=bevel;mod.segments=3
            bpy.context.view_layer.objects.active=obj
            bpy.ops.object.modifier_apply(modifier=mod.name)
            obj.modifiers.new('weighted_normals','WEIGHTED_NORMAL')
        obj['review_layer']=layer;obj['semantic_role']=role or name
        all_objects.append(obj);return obj
    def cylinder(name,loc,radius,depth,material='wood',vertices=48,layer='lower'):
        bpy.ops.mesh.primitive_cylinder_add(vertices=vertices,radius=radius,depth=depth,location=loc)
        obj=bpy.context.object;obj.name=name;obj.data.materials.append(materials[material])
        obj['review_layer']=layer;obj['semantic_role']=name;all_objects.append(obj);return obj
    def boolean_open(wall,oid,loc,dims,kind,destination):
        cutter=box('cutter_'+oid,loc,dims,layer='temporary')
        bpy.context.view_layer.objects.active=wall
        mod=wall.modifiers.new('aperture_'+oid,'BOOLEAN');mod.operation='DIFFERENCE';mod.solver='EXACT';mod.object=cutter
        bpy.ops.object.modifier_apply(modifier=mod.name)
        all_objects.remove(cutter);bpy.data.objects.remove(cutter,do_unlink=True)
        wall['opening_ids']=wall.get('opening_ids','')+' '+oid
        openings.append({'id':oid,'kind':kind,'wall':wall.name,'location':list(loc),'cutterDimensions':list(dims),'destination':destination,'booleanApplied':True,'solver':'EXACT'})
    floor=box('room_floor',(0,6,-.12),(14.84,12.44,.24),'floor',role='sealed floor substrate')
    west=box('wall_west',(-7.31,6,1.9),(.22,12.44,3.8))
    east=box('wall_east',(7.31,6,1.9),(.22,12.44,3.8))
    south=box('wall_south',(0,-.11,1.9),(14.4,.22,3.8))
    north=box('wall_north',(0,12.11,1.9),(14.4,.22,3.8))
    ceiling=box('room_ceiling',(0,6,3.91),(14.84,12.44,.22),'shell',layer='ceiling')
    boolean_open(west,'arrival-west',(-7.31,2.1,1.35),(.7,2.6,2.7),'door','open entrance hallway, 2.4m passage depth')
    box('hall_floor',(-8.62,2.1,-.12),(2.62,3.04,.24),'floor')
    box('hall_south',(-8.62,.69,1.9),(2.62,.22,3.8))
    box('hall_north',(-8.62,3.51,1.9),(2.62,.22,3.8))
    box('hall_ceiling',(-8.62,2.1,3.91),(2.62,3.04,.22),'shell',layer='ceiling')
    box('arrival_threshold',(-7.31,2.1,.005),(.44,2.6,.01),'detail')
    for idx,(x,width) in enumerate([(-4.6,2.6),(0,2.8),(4.6,2.6)],1):
        oid=f'clerestory-{idx}'
        boolean_open(north,oid,(x,12.11,3.3),(width,.7,.6),'window','exterior view; no authored environment assigned yet')
        box(oid+'_sill',(x,11.96,2.99),(width+.12,.4,.08),'wood')
        # Glazing is an explicit opening infill, not a false decorative aperture.
        glass=box(oid+'_glazing',(x,12.18,3.3),(width,.012,.6),'glass')
        glass['opening_id']=oid
    # Shared dining table replaces the sofa at the owner's explicit request.
    # Nine friends on the far side, eight on the near side; original pairs stay together.
    ids=['lena','dima','vitya','kazar','alice','nikita','yulia','artemiy','marina','misha','diana','khariton','natasha','vova','jenya','sasha','kira']
    seats=[]
    box('communal_table_top',(0,6.8,.735),(10.8,2.4,.09),'table',.12)
    for x in (-4.65,-2.325,0,2.325,4.65):
        for y in (6.0,7.6):
            box(f'dining_table_leg_{x}_{y}',(x,y,.345),(.12,.12,.69),'wood',.025)
        box(f'dining_table_trestle_{x}',(x,6.8,.16),(.14,1.85,.12),'wood',.025)
    for row,count,y,front in [('far',9,8.7,-1),('near',8,4.9,1)]:
        for i in range(count):
            x=(i-(count-1)/2)*1.2
            n=len(seats)+1;actor=ids[n-1]
            box(f'chair_seat_{n:02d}',(x,y,.445),(.64,.64,.09),'seat',.055)
            box(f'chair_back_{n:02d}',(x,y-front*.30,.82),(.64,.09,.72),'sofa',.055)
            for dx in (-.24,.24):
                for dy in (-.24,.24):
                    box(f'chair_leg_{n}_{dx}_{dy}',(x+dx,y+dy,.20),(.06,.06,.4),'wood',.012)
            seats.append({'seat':n,'actorId':actor,'row':row,'anchor':[x,y,.49],'facing':[0,front,0],'clearanceBounds':[.8,.9,1.6]})
            # Placeholder place-setting geometry indicates reach, not actual food assets.
            place_y=6.8+(0.86 if row=='far' else -.86)
            cylinder(f'place_{n:02d}',(x,place_y,.79),.15,.018,'paper',32)
            cylinder(f'cup_{n:02d}',(x+.29,place_y,.855),.055,.15,'paper',24)
    box('laptop_base',(0,6.8,.805),(.68,.42,.042),'metal',.015)
    screen=box('laptop_screen',(0,6.99,1.03),(.68,.035,.43),'detail',.018)
    screen.rotation_euler.x=math.radians(-12)
    # Coordinated media cabinets with a real clear separation and dressed shelves.
    cabinet_records=[]
    for cid,x in [('books',4.1),('cinema',5.95)]:
        group=[]
        for part,loc,dims in [('back',(x,11.88,1.30),(1.65,.04,2.6)),('left',(x-.79,11.65,1.30),(.07,.5,2.6)),('right',(x+.79,11.65,1.30),(.07,.5,2.6)),('base',(x,11.65,.045),(1.65,.5,.09)),('top',(x,11.65,2.555),(1.65,.5,.09))]:
            group.append(box(cid+'_'+part,loc,dims,'wood',.018).name)
        for row,z in enumerate((.62,1.25,1.89)):
            box(f'{cid}_shelf_{row}',(x,11.65,z),(1.57,.48,.055),'wood',.012)
            # Plausible separated spines/cases, without fake covers or labels.
            count=9 if cid=='books' else 7
            for col in range(count):
                height=(.30+.05*((col+row)%3)) if cid=='books' else .32
                width=.08 if cid=='books' else .10
                bx=x-.63+col*(.135 if cid=='books' else .15)
                box(f'{cid}_case_{row}_{col}',(bx,11.56,z+.03+height/2),(width,.20,height),'detail' if (col+row)%3 else 'paper',.006)
        cabinet_records.append({'id':cid,'center':[x,11.65,1.3],'dimensions':[1.65,.5,2.6],'semanticFront':[0,-1,0]})
    # Board and photo frames are physical wall fixtures with visible thickness.
    box('announcements_board',(-5.1,11.94,2.1),(3,.12,1.9),'wood',.04)
    box('announcements_sheet',(-5.1,11.871,2.47),(2.7,.018,.67),'paper')
    box('help_sheet',(-5.1,11.871,1.72),(2.7,.018,.61),'paper')
    for idx,(x,z,w,h,angle) in enumerate([(-1.15,2.48,1.04,.72,-6),(.05,2.65,1.15,.76,5),(1.15,2.40,.91,.70,-5),(-.6,1.88,1.08,.70,3),(.65,1.83,.94,.68,-4)]):
        frame=box(f'photo_frame_{idx}',(x,11.98,z),(w,.04,h),'paper',.018)
        frame.rotation_euler.y=math.radians(angle)
        panel=box(f'photo_panel_{idx}',(x,11.954,z),(w*.85,.012,h*.76),'detail')
        panel.rotation_euler.y=math.radians(angle)
    box('club_sign_reserve',(0,11.9675,3.00),(3.3,.065,.35),'detail',.06,role='future existing dear friends identity; no fake text in review')
    # A restrained, physically suspended center pendant gives a ceiling projection.
    cylinder('pendant_rose',(0,6.8,3.78),.12,.04,'metal',32,'ceiling')
    cylinder('pendant_cord',(0,6.8,3.59),.012,.36,'detail',12,'ceiling')
    shade_obj=cylinder('pendant_shade',(0,6.8,3.35),.34,.18,'metal',64,'ceiling')
    shade_obj['attachment']='visible cord to ceiling rose'
    # Camera helper and render visibility are recorded separately from the shell.
    cameras={}
    def camera(name,loc,target,kind='PERSP',ortho=None,lens=24):
        data=bpy.data.cameras.new(name);data.type=kind;data.lens=lens;data.sensor_width=36;data.clip_start=.03;data.clip_end=200
        if ortho:data.ortho_scale=ortho
        obj=bpy.data.objects.new(name,data);scene.collection.objects.link(obj);obj.location=loc
        obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler();cameras[name]=obj;return obj
    production=camera('production_camera',(0,-4.5,8),(0,6.8,.5),lens=27)
    camera('animation_top_camera',(0,6.8,19),(0,6.8,0),'ORTHO',16.0)
    camera('layout_camera',(-16,-13,18),(-1,6,.9),'ORTHO',23.5)
    camera('floor_plan_camera',(-1.25,6,23),(-1.25,6,0),'ORTHO',19.2)
    camera('ceiling_plan_camera',(-1.25,6,-20),(-1.25,6,3.8),'ORTHO',19.2)
    cameras['ceiling_plan_camera'].scale.x=-1
    # Looking from each interior side toward its facing wall; roofs are excluded.
    camera('north_elevation',(0,-18,1.9),(0,12,1.9),'ORTHO',16)
    camera('south_elevation',(0,30,1.9),(0,0,1.9),'ORTHO',16)
    camera('west_elevation',(20,6,1.9),(-7.31,6,1.9),'ORTHO',14)
    camera('east_elevation',(-20,6,1.9),(7.31,6,1.9),'ORTHO',14)
    scene.render.resolution_x=1440;scene.render.resolution_y=900
    scene.camera=production
    bpy.context.view_layer.update()
    corners=[Vector((x,y,z)) for x in (-5.5,5.5) for y in (4.45,9.15) for z in (0,1.9)]
    projected=[world_to_camera_view(scene,production,p) for p in corners]
    camera_bounds={'xMin':min(v.x for v in projected),'xMax':max(v.x for v in projected),'yMin':min(v.y for v in projected),'yMax':max(v.y for v in projected),'allInFront':all(v.z>0 for v in projected),'targetViewport':[1440,900]}
    if not(0<=camera_bounds['xMin']<camera_bounds['xMax']<=1):
        raise RuntimeError('Production camera crops shared-table reserve: '+str(camera_bounds))
    default_hide={o.name:False for o in all_objects}
    def render(path,cam,hidden=(),only=None,size=(1280,800)):
        names=set(hidden)
        for obj in all_objects:obj.hide_render=obj.name in names or (only is not None and obj.name not in only)
        scene.camera=cameras[cam];scene.render.resolution_x,scene.render.resolution_y=size
        scene.render.filepath=str(output/path)
        plan_view=str(path).startswith('plans/')
        old_colors={name:tuple(mat.diffuse_color) for name,mat in materials.items()}
        if plan_view:
            shade.light='FLAT';shade.show_shadows=False
            for mat in materials.values():mat.diffuse_color=(.97,.97,.97,1)
        bpy.ops.render.render(write_still=True)
        if plan_view:
            for name,color in old_colors.items():materials[name].diffuse_color=color
            shade.light='STUDIO';shade.show_shadows=True
    ceiling_names={o.name for o in all_objects if o['review_layer']=='ceiling'}
    shell_names={'wall_north','wall_south','wall_east','wall_west','room_floor','room_ceiling','hall_floor','hall_south','hall_north','hall_ceiling'}
    render('renders/production-camera.png','production_camera',hidden=ceiling_names|{'wall_south'},size=(1440,900))
    render('renders/animation-top.png','animation_top_camera',only={o.name for o in all_objects if o.name.startswith(('communal_table','dining_table','chair_','place_','cup_','laptop_'))},size=(1440,900))
    render('renders/layout-perspective.png','layout_camera',hidden=ceiling_names|{'wall_south','wall_west','hall_south'})
    render('plans/floor-plan.png','floor_plan_camera',hidden=ceiling_names,size=(1280,1000))
    render('plans/reflected-ceiling.png','ceiling_plan_camera',only=ceiling_names|{'wall_west','wall_east','wall_north','wall_south'},size=(1280,1000))
    elevations={
      'north':{'wall_north'}|{o.name for o in all_objects if o.location.y>11.3 and o['review_layer']!='ceiling'},
      'south':{'wall_south'},
      'west':{'wall_west','hall_floor','hall_south','hall_north'},
      'east':{'wall_east'},
    }
    for side,names in elevations.items():
        render(f'plans/elevation-{side}.png',side+'_elevation',only=names,size=(1280,500))
    # Explicitly provisional material direction, never a final Form/runtime proof.
    review_palette={'shell':(.13,.085,.20,1),'floor':(.38,.235,.15,1),'sofa':(.40,.025,.09,1),'seat':(.59,.045,.14,1),'table':(.36,.18,.08,1),'wood':(.32,.15,.065,1),'paper':(.94,.84,.64,1),'detail':(.065,.055,.09,1),'glass':(.18,.24,.40,1),'metal':(.24,.20,.18,1)}
    neutral_colors={name:tuple(mat.diffuse_color) for name,mat in materials.items()}
    for name,color in review_palette.items():materials[name].diffuse_color=color
    render('renders/material-direction-preview.png','production_camera',hidden=ceiling_names|{'wall_south'},size=(1440,900))
    render('renders/animation-top.png','animation_top_camera',only={'room_floor'}|{o.name for o in all_objects if o.name.startswith(('communal_table','dining_table','chair_','place_','cup_','laptop_'))},size=(1440,900))
    for name,color in neutral_colors.items():materials[name].diffuse_color=color
    for obj in all_objects:obj.hide_render=obj.name in ceiling_names|{'wall_south'}
    scene.camera=production;scene.render.resolution_x=1440;scene.render.resolution_y=900
    bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=str(output/'review-geometry.blend'))
    triangles=0
    for obj in all_objects:
        mesh=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
        triangles+=sum(len(p.vertices)-2 for p in mesh.polygons)
        obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
    objects=[]
    for obj in all_objects:
        bounds=[obj.matrix_world@Vector(corner) for corner in obj.bound_box]
        objects.append({'id':obj.name,'role':obj['semantic_role'],'layer':obj['review_layer'],'bounds':{'min':[min(v[i] for v in bounds) for i in range(3)],'max':[max(v[i] for v in bounds) for i in range(3)]}})
    metadata={'stage':'function engineering review only','units':'metres','roomInnerBounds':{'min':[-7.2,0,0],'max':[7.2,12,3.8]},'wallThickness':.22,'camera':{'location':list(production.location),'target':[0,6.8,.5],'lensMm':27,'requestedLensMm':27,'framingAdjustment':'Elevated cutaway camera for shared table; ceiling and front wall hidden in review','sensorMm':36,'viewport':[1440,900],'heroProjection':camera_bounds},'triangleCount':triangles,'objectCount':len(all_objects),'seats':seats,'cabinets':cabinet_records,'openings':openings,'heroReserve':{'center':[0,6.8,.95],'dimensions':[11,4.7,1.9]},'circulation':{'entranceClearWidth':2.6,'hallwayDepth':2.4,'sideClearance':1.8,'nearRowToFrontWall':4.45,'farRowToCabinets':2.25},'reviewVisibility':{'layoutPerspective':['ceiling','south wall','west wall','hall south wall hidden as documented engineering section'],'floorPlan':['ceiling hidden to reveal actual lower-room geometry'],'reflectedCeiling':['only actual ceiling objects and wall substrate']},'materialPreview':{'path':'renders/material-direction-preview.png','status':'provisional Function-stage palette only','lighting':'Workbench studio illumination, not baked or runtime lighting','palette':{name:list(color) for name,color in review_palette.items()}},'exports':[],'finalComposition':False,'avatarsAuthored':False,'objects':objects}
    (output/'geometry-metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print('ROOM_REVIEW_READY',json.dumps({'output':str(output),'triangles':triangles,'objects':len(all_objects),'heroProjection':camera_bounds}))


if __name__=='__main__':main()
