# Adapted from felixgwu's PR here:
# https://github.com/felixgwu/vision/blob/cf491d301f62ae9c77ff7250fb7def5cd55ec963/torchvision/datasets/camvid.py

import os
import torch
import torch.utils.data as data
import numpy as np
from PIL import Image
from torchvision.datasets.folder import is_image_file, default_loader
from ...utils.exceptions import assert_
from ..transform.base import Compose
from ..transform.generic import Normalize, NormalizeRange, Cast, AsTorchBatch
from ..transform.image import \
    RandomSizedCrop, RandomGammaCorrection, RandomFlip, Scale, PILImage2NumPyArray


CAMVID_CLASSES = ['Sky',
                  'Building',
                  'Column-Pole',
                  'Road',
                  'Sidewalk',
                  'Tree',
                  'Sign-Symbol',
                  'Fence',
                  'Car',
                  'Pedestrain',
                  'Bicyclist',
                  'Void']

# weights when using median frequency balancing used in SegNet paper
# https://arxiv.org/pdf/1511.00561.pdf
# The numbers were generated by:
# https://github.com/yandex/segnet-torch/blob/master/datasets/camvid-gen.lua
CAMVID_CLASS_WEIGHTS = [0.58872014284134,
                        0.51052379608154,
                        2.6966278553009,
                        0.45021694898605,
                        1.1785038709641,
                        0.77028578519821,
                        2.4782588481903,
                        2.5273461341858,
                        1.0122526884079,
                        3.2375309467316,
                        4.1312313079834,
                        0]
# mean and std
CAMVID_MEAN = [0.41189489566336, 0.4251328133025, 0.4326707089857]
CAMVID_STD = [0.27413549931506, 0.28506257482912, 0.28284674400252]

CAMVID_CLASS_COLORS = [
    (128, 128, 128),
    (128, 0, 0),
    (192, 192, 128),
    (128, 64, 128),
    (0, 0, 192),
    (128, 128, 0),
    (192, 128, 128),
    (64, 64, 128),
    (64, 0, 128),
    (64, 64, 0),
    (0, 128, 192),
    (0, 0, 0),
]


def make_dataset(dir):
    images = []
    for root, _, fnames in sorted(os.walk(dir)):
        for fname in fnames:
            if is_image_file(fname):
                path = os.path.join(root, fname)
                item = path
                images.append(item)
    return images


def label_to_long_tensor(pic):
    label = torch.ByteTensor(torch.ByteStorage.from_buffer(pic.tobytes()))
    label = label.view(pic.size[1], pic.size[0], 1)
    label = label.transpose(0, 1).transpose(0, 2).squeeze().contiguous().long()
    return label


def label_to_pil_image(label):
    label = label.unsqueeze(0)
    colored_label = torch.zeros(3, label.size(1), label.size(2)).byte()
    for i, color in enumerate(CAMVID_CLASS_COLORS):
        mask = label.eq(i)
        for j in range(3):
            colored_label[j].masked_fill_(mask, color[j])
    npimg = colored_label.numpy()
    npimg = np.transpose(npimg, (1, 2, 0))
    mode = None
    if npimg.shape[2] == 1:
        npimg = npimg[:, :, 0]
        mode = "L"

    return Image.fromarray(npimg, mode=mode)


class CamVid(data.Dataset):
    SPLIT_NAME_MAPPING = {'train': 'train',
                          'training': 'train',
                          'validate': 'val',
                          'val': 'val',
                          'validation': 'val',
                          'test': 'test',
                          'testing': 'test'}
    # Dataset statistics
    CLASS_WEIGHTS = CAMVID_CLASS_WEIGHTS
    CLASSES = CAMVID_CLASSES
    MEAN = CAMVID_MEAN
    STD = CAMVID_STD

    def __init__(self, root, split='train',
                 image_transform=None, label_transform=None, joint_transform=None,
                 download=False, loader=default_loader):
        # Validate
        assert_(split in self.SPLIT_NAME_MAPPING.keys(),
                "`split` must be one of {}".format(set(self.SPLIT_NAME_MAPPING.keys())),
                KeyError)
        # Root directory and split
        self.root_directory = root
        self.split = self.SPLIT_NAME_MAPPING.get(split)
        # Utils
        self.image_loader = loader
        # Transforms
        self.image_transform = image_transform
        self.label_transform = label_transform
        self.joint_transform = joint_transform
        # For when we implement download:
        if download:
            self.download()
        # Make dataset with paths to the image
        self.image_paths = make_dataset(os.path.join(self.root_directory, self.split))

    def __getitem__(self, index):
        path = self.image_paths[index]
        image = self.image_loader(path)
        label = Image.open(path.replace(self.split, self.split + 'annot'))
        # Apply transforms
        if self.image_transform is not None:
            image = self.image_transform(image)
        if self.label_transform is not None:
            label = self.label_transform(label)
        if self.joint_transform is not None:
            image, label = self.joint_transform(image, label)
        return image, label

    def __len__(self):
        return len(self.image_paths)

    def download(self):
        # TODO: please download the dataset from
        # https://github.com/alexgkendall/SegNet-Tutorial/tree/master/CamVid
        raise NotImplementedError


def get_camvid_loaders(root_directory, train_batch_size=1, validate_batch_size=1,
                       test_batch_size=1, num_workers=2):
    # Make transforms
    image_transforms = Compose(PILImage2NumPyArray(),
                               NormalizeRange(),
                               RandomGammaCorrection(),
                               Normalize(mean=CAMVID_MEAN, std=CAMVID_STD))
    label_transforms = PILImage2NumPyArray()
    joint_transforms = Compose(RandomSizedCrop(ratio_between=(0.6, 1.0),
                                               preserve_aspect_ratio=True),
                               # Scale raw image back to the original shape
                               Scale(output_image_shape=(360, 480),
                                     interpolation_order=3, apply_to=[0]),
                               # Scale segmentation back to the original shape
                               # (without interpolation)
                               Scale(output_image_shape=(360, 480),
                                     interpolation_order=0, apply_to=[1]),
                               RandomFlip(allow_ud_flips=False),
                               # Cast raw image to float
                               Cast('float', apply_to=[0]),
                               # Cast label image to long
                               Cast('long', apply_to=[1]),
                               AsTorchBatch(2, add_channel_axis_if_necessary=False))
    # Build datasets
    train_dataset = CamVid(root_directory, split='train',
                           image_transform=image_transforms,
                           label_transform=label_transforms,
                           joint_transform=joint_transforms)
    validate_dataset = CamVid(root_directory, split='validate',
                              image_transform=image_transforms,
                              label_transform=label_transforms,
                              joint_transform=joint_transforms)
    test_dataset = CamVid(root_directory, split='test',
                          image_transform=image_transforms,
                          label_transform=label_transforms,
                          joint_transform=joint_transforms)
    # Build loaders
    train_loader = data.DataLoader(train_dataset, batch_size=train_batch_size,
                                   shuffle=True, num_workers=num_workers, pin_memory=True)
    validate_loader = data.DataLoader(validate_dataset, batch_size=validate_batch_size,
                                      shuffle=True, num_workers=num_workers, pin_memory=True)
    test_loader = data.DataLoader(test_dataset, batch_size=test_batch_size,
                                  shuffle=True, num_workers=num_workers, pin_memory=True)
    return train_loader, validate_loader, test_loader
