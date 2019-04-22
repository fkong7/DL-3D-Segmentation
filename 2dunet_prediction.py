# -*- coding: utf-8 -*-
"""2dUnet_prediction.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1wJsewXWlO-4GUti6zTTQ0-WGtd3HXbmi
"""

import os
import glob

import numpy as np

from sklearn.model_selection import train_test_split
import matplotlib.image as mpimg
from PIL import Image

import tensorflow as tf
import tensorflow.contrib as tfcontrib
from tensorflow.python.keras import models as models_keras

import SimpleITK as sitk 
from preProcess import swapLabelsBack
from utils import getTrainNLabelNames
from scipy.stats import mode
from skimage.transform import resize
from loss import bce_dice_loss, dice_loss
from tensorflow.python.keras import backend as K
from model import UNet2D
"""#Prediction"""

from preProcess import RescaleIntensity
def data_preprocess_intensity(image_vol_fn, m):
    img = sitk.ReadImage(image_vol_fn)
    image_vol = sitk.GetArrayFromImage(img)
    original_shape = image_vol.shape
    if m =="mr":
        image_vol = np.moveaxis(image_vol,0,-1)
 
    ori = img.GetOrigin()
    space = img.GetSpacing()
    direc = img.GetDirection()
    
    image_vol = RescaleIntensity(image_vol, m)
    
    image_info = (ori, space, direc)
    
    return image_vol, original_shape, image_info

def data_preprocess_scale(image_vol, view, size):
    shape = [size, size, size]
    shape[view] = image_vol.shape[view]
    image_vol_resize = resize(image_vol, tuple(shape))
    return image_vol_resize

def model_output(model, im_vol, view, modality,ori_shape):
    im_vol = np.moveaxis(im_vol, view, 0)
    #need to partition due to OOM
    num = 2
    batch_size = int(im_vol.shape[0]/num)
    #TO-DO: now hard code number of classes and number of partition
    prob = np.zeros((*im_vol.shape,8))
    prob[0:batch_size] = model.predict(np.expand_dims(im_vol[0:batch_size], axis=-1))
    prob[batch_size:] = model.predict(np.expand_dims(im_vol[batch_size:], axis=-1))
    prob = np.moveaxis(prob, 0, view)
    if modality=="mr":
        prob = np.moveaxis(prob, 2, 0)
    #TO-DO: need to speed up
    prob_resize = np.zeros((*ori_shape,prob.shape[-1]))
    for i in range(prob.shape[-1]):
        prob_resize[:,:,:,i] = resize(prob[:,:,:,i], ori_shape, order=1)
    return prob_resize

def model_output_no_resize(model, im_vol, view, modality):
    im_vol = np.moveaxis(im_vol, view, 0)
    prob = model.predict(np.expand_dims(im_vol, axis=-1))
    prob = np.moveaxis(prob, 0, view)
    if modality=="mr":
        prob = np.moveaxis(prob, 2, 0)
    return prob

def average_ensemble(models, views, modality, im_vol, ori_shape):
    prob = list()
    for i in range(len(models)):
        prob.append(model_output(models[i], im_vol, views[i], modality, ori_shape))
    avg = np.mean(np.array(prob), axis=0)
    return avg

def predictVol(prob,labels):
    #im_vol, ori_shape, info = data_preprocess_test(image_vol_fn, view, 256, modality)
    predicted_label = np.argmax(prob, axis=-1)

    predicted_label = swapLabelsBack(labels,predicted_label)
    return predicted_label


"""#Compute Dice Scores"""

from scipy.spatial.distance import dice
def dice_score(pred, true):
  pred = pred.astype(np.int)
  true = true.astype(np.int)  
  num_class = np.unique(true)
  dice_out = [None]*len(num_class)
  
  for i in range(len(num_class)):
    pred_i = pred==num_class[i]
    true_i = true==num_class[i]
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

def majority_vote(volume_list):
    values, counts = np.unique(volume_list,return_counts = True)
    ind = np.argmax(counts)
    return values[ind]

class ImageLoader:
    #This is a class that loads in the filenames of the image volume and mask volume
    def __init__(self, modality, data_folder):
        self.modality = modality
        self.data_folder = data_folder
    def set_modality(self, modality):
        self.modality = modality
    def set_datafolder(self, data_folder):
        self.data_folder = data_folder
    def load_imagefiles(self):
        x_train_filenames = []
        y_train_filenames = []
        for subject_dir in sorted(glob.glob(os.path.join(self.data_folder,self.modality+'_train','*.nii.gz'))):
            x_train_filenames.append(os.path.realpath(subject_dir))
        for subject_dir in sorted(glob.glob(os.path.join(self.data_folder ,self.modality+'_train_masks','*.nii.gz'))):
            y_train_filenames.append(os.path.realpath(subject_dir))
        print("Number of testing volumes %d" % len(x_train_filenames))
        print("Number of mask volumes %d" % len(y_train_filenames))
        self.x_filenames = x_train_filenames
        self.y_filenames = y_train_filenames
        return self.x_filenames, self.y_filenames 

class Prediction:
    #This is a class to get 3D volumetric prediction from the 2DUNet model
    def __init__(self, unet, model,modality,view,image_vol_fn,label_vol_fn):
        self.unet=unet
        self.models=model
        self.modality=modality
        self.views=view
        self.image_name = image_vol_fn
        self.y_name = label_vol_fn
        self.image_vol = None
        self.label_vol = None
        self.prediction = None
        self.dice_score = None
        self.original_shape = None
        self.image_info = None
        assert len(self.models)==len(self.views), "Missing view attributes for models"

    def set_model(self,model):
        self.models=model
    def set_modality(self,modality):
        self.modality=modality
    def set_view(self,view):
        self.views=view
    def set_image_name(self, image_vol_fn):
        self.image_name = image_vol_fn

    def set_label_name(self, label_vol_fn):
        self.y_name = label_vol_fn

    def load_label(self):
        labels = sitk.GetArrayFromImage(sitk.ReadImage(self.y_name))
        labels[labels==421]=420
        self.label_vol = labels

    def process_image(self):
        self.image_vol, self.original_shape, self.image_info = \
               data_preprocess_intensity(self.image_name,self.modality)

    def volume_prediction_majority_vote(self, size):
        if self.image_vol is None:
           self.process_image() 
        if self.label_vol is None:
           self.load_label()
        prediction = [None]*len(self.models)
        for i, model in enumerate(self.models):
            image_vol_resize = data_preprocess_scale(self.image_vol, self.views[i], size)
            prob = model_output(model, image_vol_resize, self.views[i], self.modality, self.original_shape)
            tmp_pred_vol = predictVol(prob,  self.label_vol)

        if len(self.models)!=1:
            x, y, z = tmp_pred_vol.shape
            prediction[i] = tmp_pred_vol.reshape(x*y*z)
            self.prediction = np.apply_along_axis(majority_vote, 0, np.array(prediction)).reshape(x,y,z)
        #self.prediction = mode(np.array(prediction),axis=0)[0]
        return self.prediction

    def volume_prediction_average(self, size):
        if self.image_vol is None:
           self.process_image() 
        if self.label_vol is None:
           self.load_label()
        prob = np.zeros((*self.label_vol.shape,8))
        unique_views = np.unique(self.views)
        for view in unique_views:
            indices = np.where(self.views==view)[0]
            predict_shape = [size,size,size,8]
            predict_shape[view] = self.image_vol.shape[view]
            prob_view = np.zeros(predict_shape)
            if self.modality=="mr":
                prob_view = np.moveaxis(prob_view, 2, 0)
            for i in indices:
                model_path = self.models[i]
                image_vol_resize = data_preprocess_scale(self.image_vol, self.views[i], size)
                (self.unet).load_weights(model_path)
                prob_view+=model_output_no_resize(self.unet, image_vol_resize, self.views[i], self.modality)
            prob_resize = np.zeros(prob.shape)
            for i in range(prob.shape[-1]):
                prob_resize[:,:,:,i] = resize(prob_view[:,:,:,i], self.original_shape, order=1)
            prob += prob_resize
            #del model
            #K.clear_session()
        avg = prob/len(self.models)
        self.prediction = predictVol(avg, self.label_vol)
        return self.prediction
    
    def volume_prediction_single(self, size):
        if self.image_vol is None:
           self.process_image() 
        if self.label_vol is None:
           self.load_label()
        image_vol_resize = data_preprocess_scale(self.image_vol, self.views[0], size)
        prob = model_output_no_resize(self.models[0],image_vol_resize, self.views[0], self.modality)
        pred = predictVol(prob, self.label_vol)
        self.prediction = resize(pred, self.original_shape, order=0)
        return self.prediction

    def dice(self):
        if self.label_vol is None:
            self.load_label()
        self.dice_score = dice_score(self.prediction, self.label_vol)
        return self.dice_score
    def write_prediction(self, out_fn):
        ori, space, direc = self.image_info
        out_im = sitk.GetImageFromArray(self.prediction)
        out_im.SetOrigin(ori)
        out_im.SetSpacing(space)
        out_im.SetDirection(direc)
      
        sitk.WriteImage(sitk.Cast(out_im, sitk.sitkInt16), out_fn)





def modelEnsemble(folder_postfix, model_postfix, modality, view_names, view_attributes, data_folder, data_out_folder, base_folder, write=False, mode='single'):
    img_shape = (256, 256, 1)
    num_class = 8
    inputs, outputs = UNet2D(img_shape, num_class)
    unet = models_keras.Model(inputs=[inputs], outputs=[outputs])
    try:
      os.mkdir('/global/scratch/fanwei_kong/2DUNet/Logs/%s' % base_folder[-1])
      os.mkdir(data_out_folder)
    except Exception as e: print(e)
    
    for m in modality:
        #csv_path = '/global/scratch/fanwei_kong/2DUNet/Logs/%s_test-%s.csv' % (m , view_names[view])
        csv_path = '/global/scratch/fanwei_kong/2DUNet/Logs/%s/%s_test-%s.csv' % (base_folder[-1], m , folder_postfix) 
        im_loader = ImageLoader(m,data_folder)
        x_filenames, y_filenames = im_loader.load_imagefiles()
        
        dice_list = [None]*len(x_filenames)
    
        for i in range(len(x_filenames)):
            print("processing "+x_filenames[i])
            models = [None]*len(view_attributes)
            for j in range(len(view_attributes)):
                save_model_path = '/global/scratch/fanwei_kong/2DUNet/Logs/%s/weights_multi-all-%s_%s.hdf5' % (base_folder[j], view_names[j], model_postfix)
                models[j] = save_model_path
            predict = Prediction(unet, models,m,view_attributes,x_filenames[i],y_filenames[i])
            if mode=='single':
                predict.volume_prediction_single(256)
            else:
                predict.volume_prediction_average(256)
            dice_list[i] = predict.dice()
            if write:
                predict.write_prediction(os.path.join(data_out_folder,os.path.basename(x_filenames[i])))
            del predict 
        writeDiceScores(csv_path, dice_list)

def main():
    folder_postfix = "ensemble_all"
    model_postfix = "small2"
    im_base_folder = "MMWHS_small"
    base_folder = ["MMWHS_small_btstrp","MMWHS_small_btstrp2","MMWHS_small_btstrp3","MMWHS_small_btstrp","MMWHS_small_btstrp2","MMWHS_small_btstrp3","MMWHS_small_btstrp","MMWHS_small_btstrp2","MMWHS_small_btstrp3", "Ensemble_btstrp_train"]
    #base_folder = ["MMWHS_small","MMWHS_small","MMWHS_small"]
    modality = ["ct","mr"]
    names = ['axial', 'coronal', 'sagittal']
    view_attributes = [0,0,0,1,1,1,2,2,2]
    #view_attributes = [0,1,2]
    view_names = [names[i] for i in view_attributes]
    data_folder = '/global/scratch/fanwei_kong/ImageData/' + im_base_folder
    #data_out_folder = '/global/scratch/fanwei_kong/2DUNet/Logs/prediction_'+view_names[view]
    data_out_folder = '/global/scratch/fanwei_kong/2DUNet/Logs/%s/prediction_%s' % (base_folder[-1], folder_postfix)
    #save_model_path = '/global/scratch/fanwei_kong/2DUNet/Logs/weights_multi-all-%s.hdf5' % view_names[view]
    
    modelEnsemble(folder_postfix, model_postfix, modality, view_names, view_attributes, data_folder, data_out_folder, base_folder, mode="ensemble",write=True)

if __name__ == '__main__':
    import cProfile
    pr = cProfile.Profile()
    pr.enable()
    
    main()

    pr.disable()
    pr.print_stats(sort='time')
    
    
    for i in range(3,3):
        view_names_i = [view_names[i]]
        view_attributes_i = [view_attributes[i]]
        folder_postfix = view_names[i]
        base_folder_i = [base_folder[i]]
        data_out_folder = '/global/scratch/fanwei_kong/2DUNet/Logs/%s/prediction_%s' % (base_folder[i],folder_postfix)
        modelEnsemble(folder_postfix, model_postfix, modality, view_names_i, view_attributes_i, data_folder, data_out_folder, base_folder_i, mode="ensemble")

