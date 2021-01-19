'''
This script is intended to be an example of using transforms in Sagemaker. 

See how this works at:
https://docs.aws.amazon.com/sagemaker/latest/dg/processing-container-run-scripts.html

Created by Shubhom
December 2020
'''
# PyTorch Libraries
import argparse
import pathlib
import os
import pandas as pd
import shutil
from xml.etree import ElementTree
from PIL import Image
import numpy as np


def parse_annotation(filepath):
    '''
    A helper function to extract bounding box coordinates from ImageNet annotations. 
    Needs to be modified in event of multi-object recognition. 
    
    @param filepath(str): Path to xml file containing annotations
    '''
    if not os.path.exists(filepath):
        return None
    else:
        if os.path.splitext(filepath)[1] == ".xml":
            with open(filepath) as file_obj:
                tree = ElementTree.parse(file_obj)
                root = tree.getroot()
                obj = root.find("object")
                b = obj.find("bndbox")
                xmin = int(b.find("xmin").text)
                ymin = int(b.find("ymin").text)
                xmax = int(b.find("xmax").text)
                ymax = int(b.find("ymax").text)
                return xmin, ymin, xmax, ymax
        else:
            return None

        import numpy as np  

def get_train_test_inds(y, train_proportion=0.7, seed=42):
    '''
    Generates indices, making random stratified split into training set and testing sets with proportions train_proportion and (1-train_proportion) of 
    initial sample. y is any iterable indicating classes of each observation in the sample. Initial proportions of classes inside training and 
    testing sets are preserved (stratified sampling).
    
    @param y (Iterable): Iterable of columns ordered by dataset index (i.e. dataset[i, label] = y[i])
    @param train_proportion (float): Portion of data to keep as training data 
    @param seed (int): Random seed 
    '''
    
    np.random.seed(seed)
    y = np.array(y)
    train_inds = np.zeros(len(y),dtype=bool)
    test_inds = np.zeros(len(y),dtype=bool)
    values = np.unique(y)
    for value in values:
        value_inds = np.nonzero(y==value)[0]
        np.random.shuffle(value_inds)
        n = int(train_proportion*len(value_inds))
        train_inds[value_inds[:n]]=True
        test_inds[value_inds[n:]]=True
    return train_inds,test_inds

def create_path_lists(input_path, val_split, test_split, seed=42):
    '''
    Create train/val/test split based on paths. Make val_split 0 if using later cross-validation method. 
    Uses get_train_test_inds to stratify sampling by class.
    
    @param input_path(str): dataset location on Sagemaker machine local
    @param val_split (float): Portion of total dataset to use as left-out validation  (between 0 and 1)
    @param test_split(float): Portion of total dataset to use as test set (between 0 and 1)
    @param seed(int): Random seed for reproducing splits in the future
    
    @return tuple(pd.DataFrame): train, validation, and test DataFrames 
    '''
    classes = SYNSETS.keys()
    imgs = {}
    for class_name in classes:
        if not os.path.exists(os.path.join(input_path, "original_images", class_name)):
            print ("Skipping class %s"%class_name)
            continue
        temp_imgs = os.listdir(os.path.join(input_path, "original_images", class_name))
        for img_path in temp_imgs:
            if not "tar" in img_path:
                name = os.path.basename(img_path.split('.')[0])
                annotation_path = os.path.join(input_path, "bounding_boxes", class_name, "Annotation", name.split("_")[0], f"{name}.xml")
                box = parse_annotation(annotation_path)
                if box is None:
                    annotation_path = None
                full_path = os.path.join(input_path, "original_images", class_name, img_path)
                is_tree = class_name in TREE_SYNSETS.keys()
                imgs[name] = (class_name, box, is_tree, full_path, annotation_path) 
                # later, we can modify this to change how non-tree species are classified. 
                    
    imgs = pd.DataFrame.from_dict(imgs, orient="index")
    imgs.columns = ["species", "bbox", "is_tree", "full_path", "annotation_path"]
    print ("Img paths preview: ")
    print (imgs.head(5))
    total_size = imgs.shape[0]
    num_annotated = imgs.loc[:, ["bbox"]].dropna().shape[0]
    num_trees = imgs[["is_tree"]].shape[0]
    # stratify by label at column 0
    
    print ("Total num images: ", total_size)
    print ("Num annotated images: ", num_annotated)
    print ("Num tree images: ", num_trees)
    nontest_idxs, test_idxs = get_train_test_inds(imgs.iloc[:, 0], train_proportion=1-val_split, seed=seed)
    train_idxs, val_idxs = get_train_test_inds(imgs.iloc[nontest_idxs, 0], train_proportion=1-(1/(1-test_split) * val_split), seed=seed)
    
    return imgs.iloc[nontest_idxs, :][train_idxs], imgs.iloc[nontest_idxs, :][val_idxs], imgs[test_idxs]


def bbox_transform(box, original_size, reshape_size):
    '''
    Given a box and a new size, return the transformed box
    TODO: Verify this functions correctly
    '''
    scale = np.divide(original_size, reshape_size)
    if box is None:
        return (0, 0, 0, 0)
    top_left = np.multiply(np.array([box[0], box[1]]), scale).astype(np.int16)
    bottom_right = np.multiply(np.array([box[2], box[3]]), scale).astype(np.int16)
    return (top_left[0], top_left[1], bottom_right[0], bottom_right[1])
    
        
def image_transform(img, size=(128,128)):
    '''
    TODO: define some image transform 
    @param (PIL Image)
    '''
    img = img.resize(size) 
    return img
    

def image_augmentation(img, bbox, size=(128,128)):
    '''
    TODO: define some image augmentations based on class imbalances
    '''
    
    mod_bbox = bbox_transform(bbox, original_size=img.size, reshape_size=size)
    resized_img = img.resize(size)  
    flip_or_mirror = np.random.uniform()
    if flip_or_mirror < 0.5:
        rot_img = resized_img.transpose(Image.FLIP_LEFT_RIGHT)
        mod_bbox = mod_bbox # TODO: Function for flipped bbox 
    else:
        rot_img = resized_img.transpose(Image.FLIP_TOP_BOTTOM)
        mod_bbox = mod_bbox # TODO: Function for flipped bbox
    return rot_img, mod_bbox

def save_from_dataframe(df, output_dir):
    '''
    Take a DataFrames produced by create_path_lists above and generates directories. Sagemaker transfers the contents of this local 
    directory upon job completion to S3. 
    f
    @param df (pd.DataFrame): DataFrame containing columns ["species", "full_path"]
    @param output_dir (str): Path to save output to 
    '''
    saved_images = {}
    for class_name in SYNSETS.keys():
        print ("Processing class ", class_name)  
        df_subset = df[df["species"] == class_name]
        class_output_path = os.path.join(output_dir, class_name)
        if not os.path.exists(class_output_path):
            os.makedirs(class_output_path)
        for row in df_subset.itertuples():
            name = row.Index
            img = Image.open(row.full_path)
            img = image_transform(img, (128,128))
            img.save(os.path.join(class_output_path, name + ".jpg"))
            mod_bbox = bbox_transform(row.bbox, img.size, (128,128))
            saved_images[name] = (os.path.join(class_output_path, name + ".jpg"), row.species, mod_bbox, row.is_tree)
    saved_images = pd.DataFrame.from_dict(saved_images, orient="index")
    saved_images.columns = ["fullpath", "species", "bbox", "is_tree"]
    saved_images.to_csv(os.path.join(output_dir, "labels.csv"))
    return saved_images
    
    
        

def augment_from_dataframe(df, output_dir, suffix="_ aug"):
    '''
    Perform augmentation similar to save_from_dataframe but with a suffix for augmented images and a predefined subsampling of images to 
    augment, if desirable. 
    
    @param df (pd.DataFrame): DataFrame containing columns ["species", "full_path"]
    @param output_dir (str): Path to save output to 
    @param suffix (str): A suffix to identify augmented images in the output directory
    '''
    # decide on augmentation rule (balance classes, preserve class distro)
    augmented_images = {}
    for class_name in SYNSETS.keys():
        df_subset = df[df["species"] == class_name]
        class_output_path = os.path.join(output_dir, class_name)
        if not os.path.exists(class_output_path):
            raise ValueError("This class hasn't been created yet un-augmented.")
        for row in df_subset.itertuples(): 
            name = row.Index
            img = Image.open(row.full_path)
            img, mod_bbox = image_augmentation(img, row.bbox, size=(128,128))
            newpath = os.path.join(class_output_path, name + suffix + ".jpg")
            img.save(newpath)
            augmented_images[name + suffix] = (newpath, row.species, mod_bbox, row.is_tree)
    augmented_images = pd.DataFrame.from_dict(augmented_images, orient="index")
    augmented_images.columns = ["fullpath", "species", "bbox", "is_tree"]
    augmented_images.to_csv(os.path.join(output_dir, "labels.csv"), mode='a')
    return None

def preprocess(args):
    '''
    A  main method  
    '''
    INPUT_PATH = os.path.join(PROCESSING_DIR, args.input_path)
    
    OUTPUT_TRAIN_PATH = os.path.join(PROCESSING_DIR, args.output_path_train)
    OUTPUT_VALIDATION_PATH = os.path.join(PROCESSING_DIR, args.output_path_validation)
    OUTPUT_TEST_PATH = os.path.join(PROCESSING_DIR, args.output_path_test)
    
    if 1 - args.val_split_ratio - args.test_split_ratio <= 0 or args.val_split_ratio > 1 or args.test_split_ratio > 1:
        raise ValueError("Poor splits defined. Check tr/val/test split hyperparams")
    
    training_paths, validation_paths, test_paths = create_path_lists(INPUT_PATH, 
                                                                     val_split=args.val_split_ratio, 
                                                                     test_split=args.test_split_ratio)
    
    
    save_from_dataframe(training_paths, OUTPUT_TRAIN_PATH)
    augment_from_dataframe(training_paths, OUTPUT_TRAIN_PATH)
    save_from_dataframe(validation_paths, OUTPUT_VALIDATION_PATH)
    save_from_dataframe(test_paths, OUTPUT_TEST_PATH)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--val-split-ratio', type=float, default=0.2)
    parser.add_argument('--test-split-ratio', type=float, default=0.2)
    parser.add_argument('--random_seed', type=int, default=42)
    parser.add_argument('--input_path', type=str, default="raw")
    parser.add_argument('--output_path_train', type=str, default="train")
    parser.add_argument('--output_path_validation', type=str, default="validation")
    parser.add_argument('--output_path_test', type=str, default="test")
    PROCESSING_DIR = "/opt/ml/processing/"
    args = parser.parse_args()
    
        # Based on https://github.com/pytorch/examples/blob/master/mnist/main.py
    TREE_SYNSETS = {
        "judas": "n12513613",
        "palm": "n12582231",
        "pine": "n11608250",
        "china tree": "n12741792",
        "fig": "n12401684",
        "cabbage": "n12478768",
        "cacao": "n12201580",
        "kapok": "n12190410",
        "iron": "n12317296",
        "linden": "n12202936",
        "pepper": "n12765115",
        "rain": "n11759853",
        "dita": "n11770256",
        "alder": "n12284262",
        "silk": "n11759404",
        "coral": "n12527738",
        "huisache": "n11757851",
        "fringe": "n12302071",
        "dogwood": "n12946849",
        "cork": "n12713866",
        "ginkgo": "n11664418",
        "golden shower": "n12492106",
        "balata": "n12774299",
        "baobab": "n12189987",
        "sorrel": "n12242409",
        "Japanese pagoda": "n12570394",
        "Kentucky coffee": "n12496427",
        "Logwood": "n12496949"
    }
    NONTREE_SYNSETS = {
        "garbage_bin": "n02747177",
        "carion_fungus": "n13040303",
        "basidiomycetous_fungus": "n13049953",
        "jelly_fungus": "n13060190",
        "desktop_computer": "n03180011",
        "laptop_computer": "n03642806",
        "cellphone": "n02992529",
        "desk": "n03179701",
        "station_wagon": "n02814533",
        "pickup_truck": "n03930630",
        "trailer_truck": "n04467665"
    }
    SYNSETS = {**TREE_SYNSETS, **NONTREE_SYNSETS}
    preprocess(args)