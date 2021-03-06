from __future__ import absolute_import, division, print_function

import argparse
import importlib
import itertools

import time
from   multiprocessing import Pool
import numpy as np
import os
import pdb
import pickle
import subprocess
import sys
import tensorflow as tf
import tensorflow.contrib.slim as slim
import threading
import scipy.misc
from skimage import color
import init_paths
from models.sample_models import *
from lib.data.synset import *
import scipy
import skimage
import transforms3d
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
from vid_task_viz import *

ON_TEST_SET = True 
IN_TRAIN_MODE = False

parser = argparse.ArgumentParser(description='Viz Single Task')

parser.add_argument('--n-parallel', dest='n_parallel',
                    help='Number of models to run in parallel', type=int)
parser.set_defaults(n_parallel=1)

parser.add_argument('--task', dest='task')
parser.set_defaults(task='NONE')

parser.add_argument('--config', dest='config')
parser.set_defaults(config='NOT_SET')

parser.add_argument('--vid', dest='vid')
parser.set_defaults(vid='4')

parser.add_argument('--low-sat', dest='low_sat', action='store_true')
parser.set_defaults(low_sat=False)

tf.logging.set_verbosity(tf.logging.ERROR)


def parse_config_dir(config_dir):
    try:
        transfer_type,_,_,config_name = config_dir.split('/')
    except ValueError:
        transfer_type,config_name = config_dir.split('/')
    is_transfer = (transfer_type != 'final')
    is_high_order = (is_transfer and transfer_type != 'rep_only_taskonomy' and transfer_type != 'full_taskonomy_beta1')
    try:
        target_task = config_name.split('__')[-3]
    except IndexError:
        target_task = config_name
    return target_task, is_transfer, is_high_order, config_name

def generate_cfg(config_dir, vid_id, args):
    target_task, is_transfer, is_high_order, config_name = parse_config_dir(config_dir)
    CONFIG_DIR = '/home/ubuntu/task-taxonomy-331b/experiments/{cfg_dir}'.format(cfg_dir=config_dir)

    ############## Load Configs ##############
    import utils
    import data.load_ops as load_ops
    from   general_utils import RuntimeDeterminedEnviromentVars
    from   data.task_data_loading import load_and_specify_preprocessors_for_representation_extraction
    cfg = utils.load_config( CONFIG_DIR, nopause=True )
    RuntimeDeterminedEnviromentVars.register_dict( cfg )
    root_dir = cfg['root_dir']
    split_file = os.path.abspath( os.path.join( root_dir, 'assets/aws_data/video{vid_id}_info.pkl'.format(vid_id=vid_id)) )
    cfg['dataset_dir'] = '/home/ubuntu'
    os.system('sudo rm /home/ubuntu/temp/*')
    low_sat_tasks = 'autoencoder curvature denoise edge2d edge3d \
    keypoint2d keypoint3d \
    reshade rgb2depth rgb2mist rgb2sfnorm \
    room_layout segment25d segment2d \
    segmentsemantic_rb class_1000 class_places'.split()

    if target_task in low_sat_tasks and args.low_sat:
        cfg['input_preprocessing_fn'] = load_ops.resize_rescale_image_low_sat_2

    cfg['train_filenames'] = split_file
    cfg['val_filenames'] = split_file
    cfg['test_filenames'] = split_file 

    if 'train_list_of_fileinfos' in cfg:
        if type(cfg['train_representations_file']) is not list:
            task = config_name.split('__')[0]
            split_file_ =  os.path.join(
                            cfg['input_cfg']['log_root'], task,
                            '{task}_vid{vid_id}_representations.pkl'.format( task=task, vid_id=vid_id ))
        else:
            split_file_ = []
            for fname in cfg['train_representations_file']:
                split_file_.append(fname.replace('val', 'vid{vid_id}'.format(vid_id = vid_id)))
            
        cfg['train_representations_file'] = split_file_
        cfg['val_representations_file'] = split_file_
        cfg['test_representations_file'] = split_file_


        split_file_ =  os.path.join(root_dir, 'assets/aws_data/video{vid_id}_fname.npy'.format(vid_id=vid_id))
        cfg['train_list_of_fileinfos'] = split_file_
        cfg['val_list_of_fileinfos'] = split_file_
        cfg['test_list_of_fileinfos'] = split_file_

    cfg['num_epochs'] = 2
    cfg['randomize'] = False
    root_dir = cfg['root_dir']
    if target_task != 'segment2d' and target_task != 'segment25d':
        cfg['num_read_threads'] = 1
    else:
        cfg['num_read_threads'] = 1
    
    print(cfg['log_root'])
    if is_transfer:
        cfg['model_path'] = tf.train.latest_checkpoint(
                os.path.join(
                    cfg['log_root'],
                    'logs',
                    'slim-train'
                ))

        # Try latest checkpoint by time
        if cfg['model_path'] is None:
            cfg['model_path'] = tf.train.latest_checkpoint(
                os.path.join(
                    cfg['log_root'],
                    'logs',
                    'slim-train',
                    'time'
                ))      

        # Try to get one saved manually
        if cfg['model_path'] is None:  
            cfg['model_path'] = os.path.join(cfg['log_root'], task, "model.permanent-ckpt") 
    else:
        if target_task != 'vanishing_point_well_defined' and target_task != 'jigsaw':
            cfg['model_path'] = os.path.join(cfg['dataset_dir'], "model_log_final", target_task,
                                             "logs/model.permanent-ckpt") 
            import tempfile
            import subprocess
            dirs, fname = os.path.split(cfg['model_path'])
            dst_dir = dirs.replace(cfg['dataset_dir'], "s3://taskonomy-unpacked-oregon")
            tmp_path = "/home/ubuntu/temp"
            tmp_fname = os.path.join(tmp_path, fname)
            aws_cp_command = "aws s3 cp {}.data-00000-of-00001 {}".format(os.path.join(dst_dir, fname), tmp_path)
            subprocess.call(aws_cp_command, shell=True)
            aws_cp_command = "aws s3 cp {}.meta {}".format(os.path.join(dst_dir, fname), tmp_path)
            subprocess.call(aws_cp_command, shell=True)
            aws_cp_command = "aws s3 cp {}.index {}".format(os.path.join(dst_dir, fname), tmp_path)
            subprocess.call(aws_cp_command, shell=True)
            cfg['model_path'] = tmp_fname
        else:
            cfg['model_path'] = os.path.join(
                    cfg['log_root'],
                    target_task,
                    'model.permanent-ckpt'
                )

        print( cfg['model_path'])
    cfg['preprocess_fn'] = load_and_specify_preprocessors_for_representation_extraction
    return cfg, is_transfer, target_task, config_name

def run_to_task(task_to):

    import general_utils
    from   general_utils import RuntimeDeterminedEnviromentVars
    import models.architectures as architectures
    from   data.load_ops import resize_rescale_image
    from   data.load_ops import rescale_image
    import utils
    from   data.task_data_loading import load_and_specify_preprocessors_for_representation_extraction
    from   data.task_data_loading import load_and_specify_preprocessors_for_input_depends_on_target
    import lib.data.load_ops as load_ops
    tf.logging.set_verbosity(tf.logging.ERROR)
   
    args = parser.parse_args()

    cfg, is_transfer, task, config_name = generate_cfg(args.config, args.vid, args)
    if task == 'class_places' or task == 'class_1000':
        synset = get_synset(task)
    if task == 'jigsaw':
        cfg['preprocess_fn'] = load_and_specify_preprocessors_for_input_depends_on_target

    print("Doing {task}".format(task=task))
    general_utils = importlib.reload(general_utils)
    tf.reset_default_graph()
    training_runners = { 'sess': tf.InteractiveSession(), 'coord': tf.train.Coordinator() }

    ############## Start dataloading workers ##############
    if is_transfer:
        get_data_prefetch_threads_init_fn = utils.get_data_prefetch_threads_init_fn_transfer
        setup_input_fn = utils.setup_input_transfer
    else:
        setup_input_fn = utils.setup_input
        get_data_prefetch_threads_init_fn = utils.get_data_prefetch_threads_init_fn
    
    ############## Set Up Inputs ##############
    # tf.logging.set_verbosity( tf.logging.INFO )
    inputs = setup_input_fn( cfg, is_training=False, use_filename_queue=False )
    RuntimeDeterminedEnviromentVars.load_dynamic_variables( inputs, cfg )
    RuntimeDeterminedEnviromentVars.populate_registered_variables()
    start_time = time.time()

    ############## Set Up Model ##############
    model = utils.setup_model( inputs, cfg, is_training=IN_TRAIN_MODE )
    m = model[ 'model' ]
    model[ 'saver_op' ].restore( training_runners[ 'sess' ], cfg[ 'model_path' ] )

    data_prefetch_init_fn = get_data_prefetch_threads_init_fn( inputs, cfg, 
        is_training=False, use_filename_queue=False )
    prefetch_threads = threading.Thread(
        target=data_prefetch_init_fn,
        args=( training_runners[ 'sess' ], training_runners[ 'coord' ] ))
    
    prefetch_threads.start()
    list_of_fname = np.load('/home/ubuntu/task-taxonomy-331b/assets/aws_data/video{}_fname.npy'.format(args.vid))
    import errno

    try:
        os.mkdir('/home/ubuntu/{}'.format(task))
        os.mkdir('/home/ubuntu/{}/vid1'.format(task))
        os.mkdir('/home/ubuntu/{}/vid2'.format(task))
        os.mkdir('/home/ubuntu/{}/vid3'.format(task))
        os.mkdir('/home/ubuntu/{}/vid4'.format(task))
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
    curr_comp = np.zeros((3,64))
    curr_fit_img = np.zeros((256,256,3))
    embeddings = []
    curr_vp = [] 
    curr_layout = []
    ############## Run First Batch ##############
    def rescale_l_for_display( batch, rescale=True ):
        '''
        Prepares network output for display by optionally rescaling from [-1,1],
        and by setting some pixels to the min/max of 0/1. This prevents matplotlib
        from rescaling the images. 
        '''
        if rescale:
            display_batch = [ rescale_image( im.copy(), new_scale=[0, 100], current_scale=[-1, 1] ) for im in batch ]
        else:
            display_batch = batch.copy()
        for im in display_batch:
            im[0,0,0] = 1.0  # Adjust some values so that matplotlib doesn't rescale
            im[0,1,0] = 0.0  # Now adjust the min
        return display_batch

    for step_num in range(inputs['max_steps'] - 1):
    #for step_num in range(20):
        #if step_num > 0 and step_num % 20 == 0:
        print(step_num)
        if is_transfer:
            ( 
                input_batch, target_batch, 
                data_idx, 
                predicted
            ) = training_runners['sess'].run( [ 
                m.input_images, m.target_images, 
                model[ 'data_idxs' ], 
                m.decoder.decoder_output] )
        else:
            ( 
                input_batch, target_batch, 
                data_idx, 
                predicted
            ) = training_runners['sess'].run( [ 
                m.input_images, m.targets, 
                model[ 'data_idxs' ], 
                m.decoder_output] )

        if task == 'segment2d' or task == 'segment25d':
            from sklearn.decomposition import PCA  
            x = np.zeros((32,256,256,3), dtype='float')
            k_embed = 8
            for i in range(predicted.shape[0]):
                embedding_flattened = np.squeeze(predicted[i]).reshape((-1,64))
                embeddings.append(embedding_flattened)
                if len(embeddings) > k_embed:
                    embeddings.pop(0)
                pca = PCA(n_components=3)
                pca.fit(np.vstack(embeddings))
                min_order = None
                min_dist = float('inf')
                copy_of_comp = np.copy(pca.components_)
                for order in itertools.permutations([0,1,2]):
                    #reordered = pca.components_[list(order), :]
                    #dist = np.linalg.norm(curr_comp-reordered)
                    pca.components_ = copy_of_comp[order, :]
                    lower_dim = pca.transform(embedding_flattened).reshape((256,256,-1))
                    lower_dim = (lower_dim - lower_dim.min()) / (lower_dim.max() - lower_dim.min())
                    dist = np.linalg.norm(lower_dim - curr_fit_img)
                    if dist < min_dist:
                        min_order = order 
                        min_dist = dist
                pca.components_ = copy_of_comp[min_order, :]
                lower_dim = pca.transform(embedding_flattened).reshape((256,256,-1))
                lower_dim = (lower_dim - lower_dim.min()) / (lower_dim.max() - lower_dim.min())
                curr_fit_img = np.copy(lower_dim)
                x[i] = lower_dim
            predicted = x
        if task == 'curvature':
            std = [31.922, 21.658]
            mean = [123.572, 120.1]
            predicted = (predicted * std) + mean
            predicted[:,0,0,:] = 0.
            predicted[:,1,0,:] = 1.
            predicted = np.squeeze(np.clip(predicted.astype(int) / 255., 0., 1. )[:,:,:,0])

        if task == 'colorization':
            maxs = np.amax(predicted, axis=-1)
            softmax = np.exp(predicted - np.expand_dims(maxs, axis=-1))
            sums = np.sum(softmax, axis=-1)
            softmax = softmax / np.expand_dims(sums, -1)

            kernel = np.load('/home/ubuntu/task-taxonomy-331b/lib/data/pts_in_hull.npy')
            gen_target_no_temp = np.dot(softmax, kernel)

            images_resized = np.zeros([0, 256, 256, 2], dtype=np.float32)
            for image in range(gen_target_no_temp.shape[0]):
                temp = scipy.ndimage.zoom(np.squeeze(gen_target_no_temp[image]), (4, 4, 1), mode='nearest')
                images_resized = np.append(images_resized, np.expand_dims(temp, axis=0), axis=0)
            inp_rescale = rescale_l_for_display(input_batch)
            output_lab_no_temp = np.concatenate((inp_rescale, images_resized), axis=3).astype(np.float64)

            for i in range(input_batch.shape[0]):
                output_lab_no_temp[i,:,:,:] = skimage.color.lab2rgb(output_lab_no_temp[i,:,:,:])
            predicted = output_lab_no_temp

        just_rescale = ['autoencoder', 'denoise', 'edge2d', 
                        'edge3d', 'keypoint2d', 'keypoint3d',
                        'reshade', 'rgb2sfnorm', 'impainting_whole']

        if task in just_rescale:
            predicted = (predicted + 1.) / 2.
            predicted = np.clip(predicted, 0., 1.)
            predicted[:,0,0,:] = 0.
            predicted[:,1,0,:] = 1.


        just_clip = ['rgb2depth', 'rgb2mist']
        if task in just_clip:
            predicted = np.exp(predicted * np.log( 2.0**16.0 )) - 1.0
            predicted = np.log(predicted) / 11.09
            predicted = ( predicted - 0.64 ) / 0.18
            predicted = ( predicted + 1. ) / 2
            predicted[:,0,0,:] = 0.
            predicted[:,1,0,:] = 1.

        if task == 'segmentsemantic_rb':
            label = np.argmax(predicted, axis=-1)
            COLORS = ('white','red', 'blue', 'yellow', 'magenta', 
                    'green', 'indigo', 'darkorange', 'cyan', 'pink', 
                    'yellowgreen', 'black', 'darkgreen', 'brown', 'gray',
                    'purple', 'darkviolet')
            rgb = (input_batch + 1.) / 2.
            preds = [color.label2rgb(np.squeeze(x), np.squeeze(y), colors=COLORS, kind='overlay')[np.newaxis,:,:,:] for x,y in zip(label, rgb)]
            predicted = np.vstack(preds) 

        if task in ['class_1000', 'class_places']:
            for file_idx, predict_output in zip(data_idx, predicted):
                to_store_name = list_of_fname[file_idx].decode('utf-8').replace('video', task)
                to_store_name = os.path.join('/home/ubuntu', to_store_name)
                sorted_pred = np.argsort(predict_output)[::-1]
                top_5_pred = [synset[sorted_pred[i]] for i in range(5)]
                to_print_pred = "Top 5 prediction: \n {}\n {}\n {}\n {} \n {}".format(*top_5_pred)
                img = Image.new('RGBA', (400, 200), (255, 255, 255))
                d = ImageDraw.Draw(img)
                fnt = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSerifCondensed.ttf', 25)
                d.text((20, 5), to_print_pred, fill=(255, 0, 0), font=fnt)
                img.save(to_store_name, 'PNG')
        elif task == 'vanishing_point_well_defined':
            counter = 0
            for file_idx, predict_output in zip(data_idx, predicted):
                to_store_name = list_of_fname[file_idx].decode('utf-8').replace('video', task)
                to_store_name = os.path.join('/home/ubuntu', to_store_name)
                curr_vp.append(plot_vanishing_point_smoothed(predict_output, (input_batch[counter] + 1. )/2., to_store_name, curr_vp))
                if len(curr_vp) > 5:
                    curr_vp.pop(0)
                counter+=1
                #scipy.misc.toimage(result, cmin=0.0, cmax=1.0).save(to_store_name)
        elif task == 'room_layout':
            mean = np.array([0.006072743318127848, 0.010272365569691076, -3.135909774145468, 
                            1.5603802322235532, 5.6228218371102496e-05, -1.5669352793761442,
                                        5.622875878174759, 4.082800262277375, 2.7713941642895956])
            std = np.array([0.8669452525283652, 0.687915294956501, 2.080513632043758, 
                            0.19627420479282623, 0.014680602791251812, 0.4183827359302299,
                                        3.991778013006544, 2.703495278378409, 1.2269185938626304])
            predicted = predicted * std + mean
            counter = 0
            for file_idx, predict_output in zip(data_idx, predicted):
                to_store_name = list_of_fname[file_idx].decode('utf-8').replace('video', task)
                to_store_name = os.path.join('/home/ubuntu', to_store_name)
                plot_room_layout(predict_output, (input_batch[counter] + 1. )/2., to_store_name, curr_layout, cube_only=True)
                curr_layout.append(predict_output)
                if len(curr_layout) > 5:
                    curr_layout.pop(0)
                #scipy.misc.toimage(result, cmin=0.0, cmax=1.0).save(to_store_name)
                counter+=1
        elif task == 'segmentsemantic_rb':
            for file_idx, predict_output in zip(data_idx, predicted):
                to_store_name = list_of_fname[file_idx].decode('utf-8').replace('video', task)
                to_store_name = os.path.join('/home/ubuntu', to_store_name)
                process_semseg_frame(predict_output, to_store_name)
        elif task == 'jigsaw':
            predicted = np.argmax(predicted, axis=1)
            counter = 0
            for file_idx, predict_output in zip(data_idx, predicted):
                to_store_name = list_of_fname[file_idx].decode('utf-8').replace('video', task)
                to_store_name = os.path.join('/home/ubuntu', to_store_name)
                perm = cfg[ 'target_dict' ][ predict_output]
                show_jigsaw((input_batch[counter] + 1. )/2., perm, to_store_name)
                counter += 1
        else:
            for file_idx, predict_output in zip(data_idx, predicted):
                to_store_name = list_of_fname[file_idx].decode('utf-8').replace('video', task)
                to_store_name = os.path.join('/home/ubuntu', to_store_name)
                scipy.misc.toimage(np.squeeze(predict_output), cmin=0.0, cmax=1.0).save(to_store_name)


    # subprocess.call('tar -czvf /home/ubuntu/{c}_{vid_id}.tar.gz /home/ubuntu/{t}/vid{vid_id}'.format(
        # c=config_name, t=task, vid_id=args.vid), shell=True)
    # subprocess.call('ffmpeg -r 29.97 -f image2 -s 256x256 -i /home/ubuntu/{t}/vid{vid_id}/0{vid_id}0%04d.png -vcodec libx264 -crf 15  {c}_{vid_id}.mp4'.format(
        # c=config_name, t=task, vid_id=args.vid), shell=True)
    subprocess.call('ffmpeg -r 29.97 -f image2 -s 256x256 -i /home/ubuntu/{t}/vid{vid_id}/0{vid_id}0%04d.png -ss 00:01:54 -t 00:00:40 -c:v libvpx-vp9 -crf 10 -b:v 128k {c}_{vid_id}.webm'.format(
        c=config_name, t=task, vid_id=args.vid), shell=True)
    # subprocess.call('ffmpeg -r 29.97 -f image2 -s 256x256 -i /home/ubuntu/{t}/vid{vid_id}/0{vid_id}0%04d.png -vcodec libx264 -crf 15  -pix_fmt yuv420p {c}_{vid_id}.mp4'.format(
        # c=config_name, t=task, vid_id=args.vid), shell=True)
    subprocess.call('sudo mkdir -p /home/ubuntu/s3/video_new/{t}'.format(t=task), shell=True)
    #subprocess.call('sudo mkdir -p /home/ubuntu/s3/video_new_all/{t}'.format(t=task), shell=True)
#     subprocess.call('aws s3 cp /home/ubuntu/{c}_{vid_id}.tar.gz s3://task-preprocessing-512-oregon/video_new_all/{t}/'.format(
         # c=config_name, t=task, vid_id=args.vid), shell=True)
    subprocess.call('aws s3 cp {c}_{vid_id}.webm s3://task-preprocessing-512-oregon/video_new/{t}/'.format(
         c=config_name, t=task, vid_id=args.vid), shell=True)

    # subprocess.call('aws s3 cp /home/ubuntu/{c}_{vid_id}.tar.gz s3://taskonomy-unpacked-oregon/video_tar_all/{t}/'.format(
        # c=config_name, t=task, vid_id=args.vid), shell=True)
    # subprocess.call('aws s3 cp {c}_{vid_id}.mp4 s3://taskonomy-unpacked-oregon/video_all/{t}/'.format(
    #     c=config_name, t=task, vid_id=args.vid), shell=True)
                
    ############## Clean Up ##############
    training_runners[ 'coord' ].request_stop()
    training_runners[ 'coord' ].join()
    print("Done: {}".format(config_name))

    ############## Reset graph and paths ##############            
    tf.reset_default_graph()
    training_runners['sess'].close()

    return

if __name__ == '__main__':
    run_to_task(None)

