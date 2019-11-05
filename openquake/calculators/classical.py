# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2014-2019 GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>.
import os
import time
import logging
import operator
import numpy

from openquake.baselib import parallel, hdf5
from openquake.baselib.general import AccumDict, block_splitter
from openquake.hazardlib.contexts import ContextMaker
from openquake.hazardlib.calc.filters import split_sources
from openquake.hazardlib.calc.hazard_curve import classical
from openquake.hazardlib.probability_map import ProbabilityMap
from openquake.commonlib import calc, util
from openquake.commonlib.source_reader import random_filtered_sources
from openquake.calculators import getters
from openquake.calculators import base

U16 = numpy.uint16
U32 = numpy.uint32
F32 = numpy.float32
F64 = numpy.float64
weight = operator.attrgetter('weight')
grp_extreme_dt = numpy.dtype([('grp_id', U16), ('grp_name', hdf5.vstr),
                             ('extreme_poe', F32)])


def get_src_ids(sources):
    """
    :returns:
       a string with the source IDs of the given sources, stripping the
       extension after the colon, if any
    """
    src_ids = []
    for src in sources:
        long_src_id = src.source_id
        try:
            src_id, ext = long_src_id.rsplit(':', 1)
        except ValueError:
            src_id = long_src_id
        src_ids.append(src_id)
    return ' '.join(set(src_ids))


def get_extreme_poe(array, imtls):
    """
    :param array: array of shape (L, G) with L=num_levels, G=num_gsims
    :param imtls: DictArray imt -> levels
    :returns:
        the maximum PoE corresponding to the maximum level for IMTs and GSIMs
    """
    return max(array[imtls(imt).stop - 1].max() for imt in imtls)


def classical_split_filter(srcs, srcfilter, gsims, params, monitor):
    """
    Split the given sources, filter the subsources and the compute the
    PoEs. Yield back subtasks if the split sources contain more than
    maxweight ruptures.
    """
    # first check if we are sampling the sources
    ss = int(os.environ.get('OQ_SAMPLE_SOURCES', 0))
    if ss:
        splits, stime = split_sources(srcs)
        srcs = random_filtered_sources(splits, srcfilter, ss)
        yield classical(srcs, srcfilter, gsims, params, monitor)
        return
    # NB: splitting all the sources improves the distribution significantly,
    # compared to splitting only the big source
    sources = []
    with monitor("filtering/splitting sources"):
        for src, _sites in srcfilter(srcs):
            splits, _stime = split_sources([src])
            sources.extend(srcfilter.filter(splits))
    if sources:
        sources.sort(key=weight)
        totsites = len(srcfilter.sitecol)
        mw = 1000 if totsites <= params['max_sites_disagg'] else 50000
        mweight = max(mw, sum(src.weight for src in sources) /
                      params['task_multiplier'])
        blocks = list(block_splitter(sources, mweight, weight))
        for block in blocks[:-1]:
            yield classical, block, srcfilter, gsims, params
        yield classical(blocks[-1], srcfilter, gsims, params, monitor)


def preclassical(srcs, srcfilter, gsims, params, monitor):
    """
    Prefilter the sources
    """
    calc_times = AccumDict(accum=numpy.zeros(3, F32))  # nrups, nsites, time
    pmap = AccumDict(accum=0)
    for src in srcs:
        t0 = time.time()
        if srcfilter.get_close_sites(src) is None:
            continue
        dt = time.time() - t0
        calc_times[src.id] += F32([src.num_ruptures, src.nsites, dt])
        for grp_id in src.src_group_ids:
            pmap[grp_id] += 0
    return dict(pmap=pmap, calc_times=calc_times, rup_data={'grp_id': []},
                extra=dict(task_no=monitor.task_no, totrups=src.num_ruptures))


@base.calculators.add('classical')
class ClassicalCalculator(base.HazardCalculator):
    """
    Classical PSHA calculator
    """
    core_task = classical_split_filter
    accept_precalc = ['classical']

    def agg_dicts(self, acc, dic):
        """
        Aggregate dictionaries of hazard curves by updating the accumulator.

        :param acc: accumulator dictionary
        :param dic: dict with keys pmap, calc_times, rup_data
        """
        with self.monitor('aggregate curves'):
            extra = dic['extra']
            self.totrups += extra['totrups']
            if extra.get('maxdist'):
                self.maxdists.append(extra['maxdist'])
            d = dic['calc_times']  # srcid -> eff_rups, eff_sites, dt
            self.calc_times += d
            srcids = []
            eff_rups = 0
            eff_sites = 0
            for srcid, rec in d.items():
                srcids.append(srcid)
                eff_rups += rec[0]
                if rec[0]:
                    eff_sites += rec[1] / rec[0]
            self.sources_by_task[extra['task_no']] = (
                eff_rups, eff_sites, U32(srcids))
            for grp_id, pmap in dic['pmap'].items():
                if pmap:
                    acc[grp_id] |= pmap
                acc.eff_ruptures[grp_id] += eff_rups

            rup_data = dic['rup_data']
            if len(rup_data['grp_id']):
                nr = len(rup_data['srcidx'])
                default = (numpy.ones(nr, F32) * numpy.nan,
                           [numpy.zeros(0, F32)] * nr)
                for k in self.rparams:
                    # variable lenght arrays
                    vlen = k.endswith('_') or k == 'probs_occur'
                    try:
                        v = rup_data[k]
                    except KeyError:
                        v = default[vlen]
                    if vlen:
                        self.datastore.hdf5.save_vlen('rup/' + k, v)
                    else:
                        dset = self.datastore['rup/' + k]
                        hdf5.extend(dset, v)
        return acc

    def acc0(self):
        """
        Initial accumulator, a dict grp_id -> ProbabilityMap(L, G)
        """
        zd = AccumDict()
        num_levels = len(self.oqparam.imtls.array)
        rparams = {'grp_id', 'srcidx', 'occurrence_rate',
                   'weight', 'probs_occur', 'sid_', 'lon_', 'lat_', 'rrup_'}
        gsims_by_trt = self.csm_info.get_gsims_by_trt()
        for sm in self.csm_info.source_models:
            for grp in sm.src_groups:
                gsims = gsims_by_trt[grp.trt]
                cm = ContextMaker(grp.trt, gsims)
                rparams.update(cm.REQUIRES_RUPTURE_PARAMETERS)
                for dparam in cm.REQUIRES_DISTANCES:
                    rparams.add(dparam + '_')
                zd[grp.id] = ProbabilityMap(num_levels, len(gsims))
        zd.eff_ruptures = AccumDict(accum=0)  # grp_id -> eff_ruptures
        self.rparams = sorted(rparams)
        for k in self.rparams:
            # variable length arrays
            vlen = k.endswith('_') or k == 'probs_occur'
            if k == 'grp_id':
                dt = U16
            elif k == 'sid_':
                dt = hdf5.vuint16
            elif vlen:
                dt = hdf5.vfloat32
            else:
                dt = F32
            self.datastore.create_dset('rup/' + k, dt)
        rparams = [p for p in self.rparams if not p.endswith('_')]
        dparams = [p[:-1] for p in self.rparams if p.endswith('_')]
        logging.info('Scalar parameters %s', rparams)
        logging.info('Vector parameters %s', dparams)
        self.sources_by_task = {}  # task_no => src_ids
        self.totrups = 0  # total number of ruptures before collapsing
        return zd

    def execute(self):
        """
        Run in parallel `core_task(sources, sitecol, monitor)`, by
        parallelizing on the sources according to their weight and
        tectonic region type.
        """
        oq = self.oqparam
        if oq.hazard_calculation_id and not oq.compare_with_classical:
            with util.read(self.oqparam.hazard_calculation_id) as parent:
                self.csm_info = parent['csm_info']
            self.calc_stats()  # post-processing
            return {}

        smap = parallel.Starmap(self.core_task.__func__)
        smap.task_queue = list(self.gen_task_queue())  # really fast
        acc0 = self.acc0()  # create the rup/ datasets BEFORE swmr_on()
        self.datastore.swmr_on()
        smap.h5 = self.datastore.hdf5
        self.calc_times = AccumDict(accum=numpy.zeros(3, F32))
        self.maxdists = []
        try:
            acc = smap.get_results().reduce(self.agg_dicts, acc0)
            self.store_rlz_info(acc.eff_ruptures)
        finally:
            if self.maxdists:
                maxdist = numpy.mean(self.maxdists)
                logging.info('Using effective maximum distance for '
                             'point sources %d km', maxdist)
            with self.monitor('store source_info'):
                self.store_source_info(self.calc_times)
            if self.sources_by_task:
                num_tasks = max(self.sources_by_task) + 1
                sbt = numpy.zeros(
                    num_tasks, [('eff_ruptures', U32),
                                ('eff_sites', U32),
                                ('srcids', hdf5.vuint32)])
                for task_no in range(num_tasks):
                    sbt[task_no] = self.sources_by_task.get(
                        task_no, (0, 0, U32([])))
                self.datastore['sources_by_task'] = sbt
                self.sources_by_task.clear()
        numrups = sum(arr[0] for arr in self.calc_times.values())
        if self.totrups != numrups:
            logging.info('Considered %d/%d ruptures', numrups, self.totrups)
        self.calc_times.clear()  # save a bit of memory
        return acc

    def gen_task_queue(self):
        """
        Build a task queue to be attached to the Starmap instance
        """
        oq = self.oqparam
        gsims_by_trt = self.csm_info.get_gsims_by_trt()
        trt_sources = self.csm.get_trt_sources(optimize_dupl=True)
        del self.csm  # save memory

        def srcweight(src):
            trt = src.tectonic_region_type
            g = len(gsims_by_trt[trt])
            m = (oq.maximum_distance(trt) / 300) ** 2
            return src.weight * g * m

        totweight = sum(sum(srcweight(src) for src in sources)
                        for trt, sources, atomic in trt_sources)
        param = dict(
            truncation_level=oq.truncation_level, imtls=oq.imtls,
            filter_distance=oq.filter_distance, reqv=oq.get_reqv(),
            collapse_factor=oq.collapse_factor, max_radius=oq.max_radius,
            pointsource_distance=oq.pointsource_distance,
            shift_hypo=oq.shift_hypo,
            task_multiplier=oq.task_multiplier,
            max_sites_disagg=oq.max_sites_disagg)
        srcfilter = self.src_filter(self.datastore.tempname)
        if oq.calculation_mode == 'preclassical':
            f1 = f2 = preclassical
        else:
            f1, f2 = classical, classical_split_filter
        C = oq.concurrent_tasks or 1
        for trt, sources, atomic in trt_sources:
            gsims = gsims_by_trt[trt]
            if atomic:
                # do not split atomic groups
                nb = 1
                yield f1, (sources, srcfilter, gsims, param)
            else:  # regroup the sources in blocks
                blocks = list(block_splitter(sources, totweight/C, srcweight))
                nb = len(blocks)
                for block in blocks:
                    logging.debug('Sending %d sources with weight %d',
                                  len(block), block.weight)
                    yield f2, (block, srcfilter, gsims, param)

            nr = sum(src.weight for src in sources)
            logging.info('TRT = %s', trt)
            logging.info('max_dist=%d km, gsims=%d, ruptures=%d, blocks=%d',
                         oq.maximum_distance(trt), len(gsims), nr, nb)

    def save_hazard(self, acc, pmap_by_kind):
        """
        Works by side effect by saving hcurves and hmaps on the datastore

        :param acc: ignored
        :param pmap_by_kind: a dictionary of ProbabilityMaps

        kind can be ('hcurves', 'mean'), ('hmaps', 'mean'),  ...
        """
        with self.monitor('saving statistics'):
            for kind in pmap_by_kind:  # i.e. kind == 'hcurves-stats'
                pmaps = pmap_by_kind[kind]
                if kind in ('hmaps-rlzs', 'hmaps-stats'):
                    # pmaps is a list of R pmaps
                    dset = self.datastore.getitem(kind)
                    for r, pmap in enumerate(pmaps):
                        for s in pmap:
                            dset[s, r] = pmap[s].array  # shape (M, P)
                elif kind in ('hcurves-rlzs', 'hcurves-stats'):
                    dset = self.datastore.getitem(kind)
                    for r, pmap in enumerate(pmaps):
                        for s in pmap:
                            dset[s, r] = pmap[s].array[:, 0]  # shape L
            self.datastore.flush()

    def post_execute(self, pmap_by_grp_id):
        """
        Collect the hazard curves by realization and export them.

        :param pmap_by_grp_id:
            a dictionary grp_id -> hazard curves
        """
        oq = self.oqparam
        trt_by_grp = self.csm_info.grp_by("trt")
        grp_name = {grp.id: grp.name for sm in self.csm_info.source_models
                    for grp in sm.src_groups}
        data = []
        with self.monitor('saving probability maps'):
            for grp_id, pmap in pmap_by_grp_id.items():
                if pmap:  # pmap can be missing if the group is filtered away
                    base.fix_ones(pmap)  # avoid saving PoEs == 1
                    trt = trt_by_grp[grp_id]
                    key = 'poes/grp-%02d' % grp_id
                    self.datastore[key] = pmap
                    self.datastore.set_attrs(key, trt=trt)
                    extreme = max(
                        get_extreme_poe(pmap[sid].array, oq.imtls)
                        for sid in pmap)
                    data.append((grp_id, grp_name[grp_id], extreme))
        if oq.hazard_calculation_id is None and 'poes' in self.datastore:
            self.datastore['disagg_by_grp'] = numpy.array(
                sorted(data), grp_extreme_dt)
            self.calc_stats()

    def calc_stats(self):
        oq = self.oqparam
        hstats = oq.hazard_stats()
        # initialize datasets
        N = len(self.sitecol.complete)
        L = len(oq.imtls.array)
        P = len(oq.poes)
        M = len(oq.imtls)
        R = len(self.rlzs_assoc.realizations)
        S = len(hstats)
        if R > 1 and oq.individual_curves or not hstats:
            self.datastore.create_dset('hcurves-rlzs', F32, (N, R, L))
            if oq.poes:
                self.datastore.create_dset('hmaps-rlzs', F32, (N, R, M, P))
        if hstats:
            self.datastore.create_dset('hcurves-stats', F32, (N, S, L))
            if oq.poes:
                self.datastore.create_dset('hmaps-stats', F32, (N, S, M, P))
        ct = oq.concurrent_tasks
        logging.info('Building hazard statistics with %d concurrent_tasks', ct)
        allargs = [  # this list is very fast to generate
            (getters.PmapGetter(self.datastore, t.sids, oq.poes),
             N, hstats, oq.individual_curves, oq.max_sites_disagg)
            for t in self.sitecol.split_in_tiles(ct)]
        self.datastore.swmr_on()
        parallel.Starmap(
            build_hazard, allargs, h5=self.datastore.hdf5
        ).reduce(self.save_hazard)


@base.calculators.add('preclassical')
class PreCalculator(ClassicalCalculator):
    """
    Calculator to filter the sources and compute the number of effective
    ruptures
    """
    core_task = preclassical


def build_hazard(pgetter, N, hstats, individual_curves,
                 max_sites_disagg, monitor):
    """
    :param pgetter: an :class:`openquake.commonlib.getters.PmapGetter`
    :param N: the total number of sites
    :param hstats: a list of pairs (statname, statfunc)
    :param individual_curves: if True, also build the individual curves
    :param max_sites_disagg: if there are less sites than this, store rup info
    :param monitor: instance of Monitor
    :returns: a dictionary kind -> ProbabilityMap

    The "kind" is a string of the form 'rlz-XXX' or 'mean' of 'quantile-XXX'
    used to specify the kind of output.
    """
    with monitor('read PoEs'):
        pgetter.init()
    imtls, poes, weights = pgetter.imtls, pgetter.poes, pgetter.weights
    L = len(imtls.array)
    R = len(weights)
    S = len(hstats)
    pmap_by_kind = {}
    if R > 1 and individual_curves or not hstats:
        pmap_by_kind['hcurves-rlzs'] = [ProbabilityMap(L) for r in range(R)]
    if hstats:
        pmap_by_kind['hcurves-stats'] = [ProbabilityMap(L) for r in range(S)]
        if poes:
            pmap_by_kind['hmaps-stats'] = [ProbabilityMap(L) for r in range(S)]
    combine_mon = monitor('combine pmaps', measuremem=False)
    compute_mon = monitor('compute stats', measuremem=False)
    for sid in pgetter.sids:
        with combine_mon:
            pcurves = pgetter.get_pcurves(sid)
        if sum(pc.array.sum() for pc in pcurves) == 0:  # no data
            continue
        with compute_mon:
            if hstats:
                arr = numpy.array([pc.array for pc in pcurves])
                for s, (statname, stat) in enumerate(hstats.items()):
                    pc = getters.build_stat_curve(arr, imtls, stat, weights)
                    pmap_by_kind['hcurves-stats'][s][sid] = pc
                    if poes:
                        hmap = calc.make_hmap(pc, pgetter.imtls, poes, sid)
                        pmap_by_kind['hmaps-stats'][s].update(hmap)
            if R > 1 and individual_curves or not hstats:
                for pmap, pc in zip(pmap_by_kind['hcurves-rlzs'], pcurves):
                    pmap[sid] = pc
                if poes:
                    pmap_by_kind['hmaps-rlzs'] = [
                        calc.make_hmap(pc, imtls, poes, sid) for pc in pcurves]
    return pmap_by_kind
