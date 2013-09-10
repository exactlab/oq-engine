#!/usr/bin/env python
# LICENSE
#
# Copyright (c) 2010-2013, GEM Foundation, G. Weatherill, M. Pagani, D. Monelli
#
# The Hazard Modeller's Toolkit (hmtk) is free software: you can redistribute
# it and/or modify it under the terms of the GNU Affero General Public License
# as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>
#
# DISCLAIMER
#
# The software Hazard Modeller's Toolkit (hmtk) provided herein is released as
# a prototype implementation on behalf of scientists and engineers working
# within the GEM Foundation (Global Earthquake Model).
#
# It is distributed for the purpose of open collaboration and in the hope that
# it will be useful to the scientific, engineering, disaster risk and software
# design communities.
#
# The software is NOT distributed as part of GEM's OpenQuake suite
# (http://www.globalquakemodel.org/openquake) and must be considered as a
# separate entity. The software provided herein is designed and implemented
# by scientific staff. It is not developed to the design standards, nor
# subject to same level of critical review by professional software developers,
# as GEM's OpenQuake software suite.
#
# Feedback and contribution to the software is welcome, and can be directed to
# the hazard scientific staff of the GEM Model Facility
# (hazard@globalquakemodel.org).
#
# The Hazard Modeller's Toolkit (hmtk) is therefore distributed WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# The GEM Foundation, and the authors of the software, assume no liability for
# use of the software.

'''
Module :mod:'hmtk.seismicity.max_magnitude.base' defines and abstract base
class for instrumental estimators of maximum magnitude
:class: hmtk.seismicity.max_magnitude.base
'''

import abc
import numpy as np
from hmtk.registry import CatalogueFunctionRegistry


def _get_observed_mmax(catalogue, config):
    '''Check see if observed mmax values are input, if not then take
    from the catalogue'''

    if not config['input_mmax']:
        # If maxmag is False then maxmag is maximum from magnitude list
        max_location = np.argmax(catalogue['magnitude'])
        obsmax = catalogue['magnitude'][max_location]
        if not isinstance(catalogue['sigmaMagnitude'], np.ndarray):
            obsmaxsig = 0.2
        else:
            obsmaxsig = catalogue['sigmaMagnitude'][max_location]
    else:
        obsmaxsig = config['input_mmax_uncertainty']
        obsmax = config['input_mmax']
    return obsmax, obsmaxsig


def _get_magnitude_vector_properties(catalogue, config):
    '''If an input minimum magnitude is given then consider catalogue
    only above the minimum magnitude - returns corresponding properties'''

    if config['input_mmin']:
        neq = np.float(np.sum(catalogue['magnitude'] >=
                              config['input_mmin'] - 1.E-7))
        mmin = config['input_mmin']
    else:
        neq = np.float(len(catalogue['magnitude']))
        mmin = np.min(catalogue['magnitude'])
    return neq, mmin


class BaseMaximumMagnitude(object):
    '''
    Abstract base class for implementation of the maximum magnitude estimation
    based on instrumental/historical seismicity
    '''
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def get_mmax(self, catalogue, config):
        '''
        Analyses the catalogue to infer the maximum magnitude from a statistical
        process
        :param catalogue:
            Earthquake catalogue as instance of the :class:
            'hmtk.seismicity.catalogue.Catalogue'

        :param dict config:
            Configuration parameters of the algorithm

        :returns:
            * Maximum magnitude (float)
            * Maximum magnitude uncertainty (float)
        '''


MAX_MAGNITUDE_METHODS = CatalogueFunctionRegistry()
