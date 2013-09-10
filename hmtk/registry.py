# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

#
# LICENSE
#
# Copyright (c) 2013, GEM Foundation
#
# The Hazard Modeller's Toolkit is free software: you can redistribute
# it and/or modify it under the terms of the GNU Affero General Public
# License as published by the Free Software Foundation, either version
# 3 of the License, or (at your option) any later version.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>
#
# DISCLAIMER The software Hazard Modeller's Toolkit (hmtk) provided
# herein is released as a prototype implementation on behalf of
# scientists and engineers working within the GEM Foundation (Global
# Earthquake Model).
#
# It is distributed for the purpose of open collaboration and in the
# hope that it will be useful to the scientific, engineering, disaster
# risk and software design communities.
#
# The software is NOT distributed as part of GEM’s OpenQuake suite
# (http://www.globalquakemodel.org/openquake) and must be considered
# as a separate entity. The software provided herein is designed and
# implemented by scientific staff. It is not developed to the design
# standards, nor subject to same level of critical review by
# professional software developers, as GEM’s OpenQuake software suite.
#
# Feedback and contribution to the software is welcome, and can be
# directed to the hazard scientific staff of the GEM Model Facility
# (hazard@globalquakemodel.org).
#
# The Hazard Modeller's Toolkit (hmtk) is therefore distributed
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License  for more details.
#
# The GEM Foundation, and the authors of the software, assume no
# liability for use of the software.


import collections
import functools
from decorator import decorator


class Registry(collections.OrderedDict):
    """
    A collection of methods added through a decorator. E.g.

    @a_registry.add('foo')
    def bar(): pass

    a_registry['foo']
    => <function bar>
    """
    def add(self, tag):
        """
        :param str tag: the tag associated to the registered object
        """
        def dec(obj):
            """:param obj: the registered object"""
            self[tag] = obj
            return obj
        return dec


class CatalogueFunctionRegistry(collections.OrderedDict):
    """
    A collection of instance methods working on catalogues.

    We assume that each instance method takes in input also a config
    object.

    The registry also holds the expected keys of the config object and
    their type information.
    """

    def check_config(self, config, fields_spec):
        for field, type_info in fields_spec.items():
            has_default = not isinstance(type_info, type)
            if field not in config and not has_default:
                raise RuntimeError(
                    "Configuration not complete. %s missing" % field)

    def set_defaults(self, config, fields_spec):
        defaults = dict([(f, d)
                         for f, d in fields_spec.items()
                         if not isinstance(d, type)])
        for field, default_value in defaults.items():
            if field not in config:
                config[field] = default_value

    def add(self, method_name, **fields):
        def class_decorator(class_obj):
            self[class_obj.__name__] = (class_obj, method_name, fields)
            original_method = getattr(class_obj, method_name)

            def method(obj, catalogue, config=None, *args, **kwargs):
                config = config or {}
                self.set_defaults(config, fields)
                self.check_config(config, fields)
                return original_method(obj, catalogue, config, *args, **kwargs)
            setattr(class_obj, method_name, method)
            return class_obj
        return class_decorator

    def __getitem__(self, key):
        class_obj, method_name, _ = super(
            CatalogueFunctionRegistry, self).__getitem__(key)
        method = getattr(class_obj, method_name)
        return functools.partial(method, class_obj())
