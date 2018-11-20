#!/usr/bin/env python
# -*- coding:utf-8 -*-
# Author: Donny You(donnyyou@163.com)
# Mobilenet models.


from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import torch
import torch.nn as nn
import torch.nn.init as init

try:
    from urllib import urlretrieve
except ImportError:
    from urllib.request import urlretrieve

from utils.tools.logger import Logger as Log


model_urls = {
    'squeezenet1_0': 'https://download.pytorch.org/models/squeezenet1_0-a815701f.pth',
    'squeezenet1_1': 'https://download.pytorch.org/models/squeezenet1_1-f364aa15.pth',
}


class Fire(nn.Module):

    def __init__(self, inplanes, squeeze_planes,
                 expand1x1_planes, expand3x3_planes):
        super(Fire, self).__init__()
        self.inplanes = inplanes
        self.squeeze = nn.Conv2d(inplanes, squeeze_planes, kernel_size=1)
        self.squeeze_activation = nn.ReLU(inplace=True)
        self.expand1x1 = nn.Conv2d(squeeze_planes, expand1x1_planes,
                                   kernel_size=1)
        self.expand1x1_activation = nn.ReLU(inplace=True)
        self.expand3x3 = nn.Conv2d(squeeze_planes, expand3x3_planes,
                                   kernel_size=3, padding=1)
        self.expand3x3_activation = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.squeeze_activation(self.squeeze(x))
        return torch.cat([
            self.expand1x1_activation(self.expand1x1(x)),
            self.expand3x3_activation(self.expand3x3(x))
        ], 1)


class AtrousFire(nn.Module):
    def __init__(self, inplanes, squeeze_planes, expand1x1_planes, expand3x3_planes):
        super(AtrousFire, self).__init__()
        self.inplanes = inplanes
        self.squeeze = nn.Conv2d(inplanes, squeeze_planes, kernel_size=1)
        self.squeeze_activation = nn.ReLU(inplace=True)
        self.expand1x1 = nn.Conv2d(squeeze_planes, expand1x1_planes, kernel_size=1)
        self.expand1x1_activation = nn.ReLU(inplace=True)
        self.expand3x3 = nn.Conv2d(squeeze_planes, expand3x3_planes, kernel_size=3, dilation=2, padding=2)
        self.expand3x3_activation = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.squeeze_activation(self.squeeze(x))
        out = torch.cat([self.expand1x1_activation(self.expand1x1(x)),
                         self.expand3x3_activation(self.expand3x3(x))], 1)
        return out


class SqueezeNet(nn.Module):

    def __init__(self):
        super(SqueezeNet, self).__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 64, kernel_size=3, stride=2),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=3, stride=2, ceil_mode=True),
            Fire(64, 16, 64, 64),
            Fire(128, 16, 64, 64),
            nn.MaxPool2d(kernel_size=3, stride=2, ceil_mode=True),
            Fire(128, 32, 128, 128),
            Fire(256, 32, 128, 128),
            nn.MaxPool2d(kernel_size=3, stride=2, ceil_mode=True),
            Fire(256, 48, 192, 192),
            Fire(384, 48, 192, 192),
            Fire(384, 64, 256, 256),
            Fire(512, 64, 256, 256),
        )

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                init.kaiming_uniform_(m.weight)
                if m.bias is not None:
                    init.constant_(m.bias, 0)

    def forward(self, x):
        x = self.features(x)
        return x


class DilatedSqueezeNet(nn.Module):
    def __init__(self):
        super(DilatedSqueezeNet, self).__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 64, kernel_size=3, stride=2),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=3, stride=2, ceil_mode=True),
            Fire(64, 16, 64, 64),
            Fire(128, 16, 64, 64),
            nn.MaxPool2d(kernel_size=3, stride=2, ceil_mode=True),
            Fire(128, 32, 128, 128),
            Fire(256, 32, 128, 128),
            nn.MaxPool2d(kernel_size=3, stride=1, ceil_mode=True),
            AtrousFire(256, 48, 192, 192),
            AtrousFire(384, 48, 192, 192),
            AtrousFire(384, 64, 256, 256),
            AtrousFire(512, 64, 256, 256),
        )

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                init.kaiming_uniform_(m.weight)
                if m.bias is not None:
                    init.constant_(m.bias, 0)

    def forward(self, x):
        x = self.features(x)
        return x


class SqueezeNetModels(object):

    def __init__(self, configer):
        self.configer = configer

    def squeezenet(self):
        """Constructs a ResNet-18 model.
        Args:
            pretrained (bool): If True, returns a model pre-trained on Places
        """
        model = SqueezeNet()
        if self.configer.get('network', 'pretrained') or self.configer.get('network', 'pretrained_model') is not None:
            if self.configer.get('network', 'pretrained_model') is not None:
                Log.info('Loading pretrained model:{}'.format(self.configer.get('network', 'pretrained_model')))
                pretrained_dict = torch.load(self.configer.get('network', 'pretrained_model'))
            else:
                pretrained_dict = self.load_url(model_urls['squeezenet1_1'])
            model_dict = model.state_dict()
            matched_dict = {k: v for k, v in pretrained_dict.items() if k in model_dict}
            Log.info('Matched Keys:{}'.format(matched_dict.keys()))
            model_dict.update(matched_dict)
            model.load_state_dict(model_dict)

        return model

    def squeezenet_dilated8(self):
        model = DilatedSqueezeNet()
        if self.configer.get('network', 'pretrained') or self.configer.get('network', 'pretrained_model') is not None:
            if self.configer.get('network', 'pretrained_model') is not None:
                Log.info('Loading pretrained model:{}'.format(self.configer.get('network', 'pretrained_model')))
                pretrained_dict = torch.load(self.configer.get('network', 'pretrained_model'))
            else:
                pretrained_dict = self.load_url(model_urls['squeezenet1_1'])
            model_dict = model.state_dict()
            matched_dict = {k: v for k, v in pretrained_dict.items() if k in model_dict}
            Log.info('Matched Keys:{}'.format(matched_dict.keys()))
            model_dict.update(matched_dict)
            model.load_state_dict(model_dict)

        return model

    def load_url(self, url, map_location=None):
        model_dir = os.path.join(self.configer.get('project_dir'), 'models/backbones/squeezenet/pretrained')
        if not os.path.exists(model_dir):
            os.makedirs(model_dir)

        filename = url.split('/')[-1]
        cached_file = os.path.join(model_dir, filename)
        if not os.path.exists(cached_file):
            Log.info('Downloading: "{}" to {}\n'.format(url, cached_file))
            urlretrieve(url, cached_file)

        Log.info('Loading pretrained model:{}'.format(cached_file))
        return torch.load(cached_file, map_location=map_location)
