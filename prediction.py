import os
import numpy as np
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))


import tensorflow as tf
import tensorflow.contrib as tfcontrib
from tensorflow.python.keras import models as models_keras

import SimpleITK as sitk 
from skimage.transform import resize
from preProcess import swapLabelsBack, resample_spacing, Resize_by_view, isometric_transform, centering, RescaleIntensity
from loss import bce_dice_loss, dice_loss
from tensorflow.python.keras import backend as K
from model import UNet2D
from imageLoader import ImageLoader
import argparse

def model_output_no_resize(model, im_vol, view, modality):
    im_vol = np.moveaxis(im_vol, view, 0)
    prob = model.predict(np.expand_dims(im_vol, axis=-1))
    prob = np.moveaxis(prob, 0, view)
    return prob

def predictVol(prob,labels):
    #im_vol, ori_shape, info = data_preprocess_test(image_vol_fn, view, 256, modality)
    predicted_label = np.argmax(prob, axis=-1)

    predicted_label = swapLabelsBack(labels,predicted_label)
    return predicted_label

from scipy.spatial.distance import dice
def dice_score(pred, true):
  pred = pred.astype(np.int)
  true = true.astype(np.int)  
  num_class = np.unique(true)
  dice_out = [None]*len(num_class)
  
  for i in range(len(num_class)):
    pred_i = pred==num_class[i]
    true_i = true==num_class[i]
    print(pred_i.shape)
    print(true_i.shape)
    sim = 1 - dice(pred_i.reshape(-1), true_i.reshape(-1))
    dice_out[i] = sim
    
  return dice_out


import csv
def writeDiceScores(csv_path,dice_outs): 
    with open(csv_path, 'w') as writeFile:
        writer = csv.writer(writeFile)
        writer.writerow( ('Bg 0', 'myo 205', 'la 420', 'lv 500', 'ra 550', 'rv 600', 'aa 820', 'pa 850') )
        for i in range(len(dice_outs)):
            writer.writerow(tuple(dice_outs[i]))
            print(dice_outs[i])
  
    writeFile.close()


class Prediction:
    #This is a class to get 3D volumetric prediction from the 2DUNet model
    def __init__(self, unet, model,modality,view,image_fn,label_fn):
        self.unet=unet
        self.models=model
        self.modality=modality
        self.views=view
        self.original_im = sitk.ReadImage(image_fn)
        self.image_vol = resample_spacing(image_fn, order=1)[0]
        try:
            self.label_vol = sitk.ReadImage(label_fn)
        except:
            self.label_vol = None
        self.prediction = None
        self.dice_score = None
        self.original_shape = None
        assert len(self.models)==len(self.views), "Missing view attributes for models"

    def volume_prediction_average(self, size):
        img_vol = sitk.GetArrayFromImage(self.image_vol)


        img_vol = RescaleIntensity(img_vol,self.modality, [750, -750])
        
        if self.label_vol is not None:
            label_vol = sitk.GetArrayFromImage(self.label_vol)
        else:
            label_vol = np.zeros(img_vol.shape)
        
        self.original_shape = img_vol.shape
        
        prob = np.zeros((*self.original_shape,8))
        unique_views = np.unique(self.views)
        
        for view in unique_views:
            indices = np.where(self.views==view)[0]
            predict_shape = [size,size,size,8]
            predict_shape[view] = img_vol.shape[view]
            prob_view = np.zeros(predict_shape)
            for i in indices:
                model_path = self.models[i]
                image_vol_resize = Resize_by_view(img_vol, self.views[i], size)
                (self.unet).load_weights(model_path)
                prob_view+=model_output_no_resize(self.unet, image_vol_resize, self.views[i], self.modality)
            prob_resize = np.zeros(prob.shape)
            for i in range(prob.shape[-1]):
                prob_resize[:,:,:,i] = resize(prob_view[:,:,:,i], self.original_shape, order=1)
            prob += prob_resize
        avg = prob/len(self.models)
        self.prediction = predictVol(avg, label_vol)
        return self.prediction

    def dice(self):
        #assuming groud truth label has the same origin, spacing and orientation as input image
        label_vol = sitk.GetArrayFromImage(self.label_vol)
        self.dice_score = dice_score(sitk.GetArrayFromImage(self.pred_label), label_vol)
        return self.dice_score
    
    def resample_prediction(self):
        #resample prediction so it matches the original image
        print(self.prediction.shape)
        im = sitk.GetImageFromArray(self.prediction)
        im.SetSpacing(self.image_vol.GetSpacing())
        im.SetOrigin(self.image_vol.GetOrigin())
        im.SetDirection(self.image_vol.GetDirection())
        self.pred_label = centering(im, self.original_im, order=0)
        return self.pred_label

    def write_prediction(self, out_fn):
        try:
            os.makedirs(os.path.dirname(out_fn))
        except:
            pass
        sitk.WriteImage(sitk.Cast(self.pred_label, sitk.sitkInt16), out_fn)

def main(modality, data_folder, data_out_folder, model_folder, view_attributes, mode):
    model_postfix = "small2"
    base_folder = [model_folder] * (len(view_attributes)+1)
    names = ['axial', 'coronal', 'sagittal']
    view_names = [names[i] for i in view_attributes]
    try:
      os.mkdir(data_out_folder)
    except Exception as e: print(e)
    
    #set up models
    img_shape = (256, 256, 1)
    num_class = 8
    inputs, outputs = UNet2D(img_shape, num_class)
    unet = models_keras.Model(inputs=[inputs], outputs=[outputs])
    
    #load image filenames
    filenames = {}
    for m in modality:
        im_loader = ImageLoader(m, data_folder, fn='_test', fn_mask=None if mode=='test' else '_test_masks', ext='*.nii.gz')
        x_filenames, y_filenames = im_loader.load_imagefiles()
        dice_list = []

        for i in range(len(x_filenames)):
            print("processing "+x_filenames[i])
            models = [os.path.realpath(model_folder) + '/weights_multi-all-%s_%s.hdf5' % (view_names[j], model_postfix) for j in range(len(view_attributes))]
            predict = Prediction(unet, models,m,view_attributes,x_filenames[i],y_filenames[i])
            predict.volume_prediction_average(256)
            predict.resample_prediction()
            if y_filenames[i] is not None:
                dice_list.append(predict.dice())
            
            predict.write_prediction(os.path.join(data_out_folder,os.path.basename(x_filenames[i])))
            del predict 
        if len(dice_list) >0:
            csv_path = os.path.join(data_out_folder, '%s_test-%s.csv' % (base_folder[-1], m))
            writeDiceScores(csv_path, dice_list)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image',  help='Name of the folder containing the image data')
    parser.add_argument('--output',  help='Name of the output folder')
    parser.add_argument('--model',  help='Name of the folder containing the trained models')
    parser.add_argument('--view', type=int, nargs='+', help='List of views for single or ensemble prediction, split by space. For example, 0 1 2  axial(0), coronal(1), sagittal(2)')
    parser.add_argument('--modality', nargs='+', help='Name of the modality, mr, ct, split by space')
    parser.add_argument('--mode', help='Test or validation (without or with ground truth label')
    args = parser.parse_args()
    print('Finished parsing...')
    
    main(args.modality, args.image, args.output, args.model, args.view, args.mode)