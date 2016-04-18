#!/usr/bin/env python

import sys
import string
import re
import time
import random
import threading
import multiprocessing
import socket
try:
    import cPickle as pickle
except ImportError:
    import pickle

MAX_PATH_NUMBER = 1

MRAI_PEER_BASED = 0
MRAI_PREFIX_BASED = 1

MRAI_JITTER = True

bgp_always_compare_med = False
ssld = False
wrate = False
GHOST_FLUSHING = False
GHOST_BUSTER = False

EPIC = False

always_mrai = False
default_local_preference = 100

default_weight = 1000
default_backup_weight_internal = 0
default_backup_weight_internal_client = 10
default_backup_weight_external = 20

backup_routing = False
backup_route_as_withdrawal = False

ALTERNATIVE_NONE = 0
ALTERNATIVE_EXIST = 1
ALTERNATIVE_BACKUP = 2

RANDOMIZED_KEY = ""

SHOW_UPDATE_RIBS = False
SHOW_RECEIVE_EVENTS = True # for debug by phil
SHOW_SEND_EVENTS = False
SHOW_FINAL_RIBS = True # for debug by phil
SHOW_DEBUG = True # for debug by phil

CHECK_LOOP = False

_link_delay_table = {}
default_link_delay_func = ["uniform", 0.01, 0.1]
default_process_delay_func = ["uniform", 0.001, 0.01]

###################################
EVENT_TERMINATE = 0
EVENT_MRAI_EXPIRE_SENDTO = 1
EVENT_UPDATE = 2
EVENT_RECEIVE = 3
EVENT_LINK_DOWN = 4
EVENT_LINK_UP = 5
EVENT_ANNOUNCE_PREFIX = 6
EVENT_WITHDRAW_PREFIX = 7

IBGP_SESSION = 0
EBGP_SESSION = 1

LINK_DOWN = -1
LINK_UP = 0

_seq_seed = 0
_systime = 0  # in microsecond


def formatTime(tm):
    return str(int(tm / 10000) * 1.0 / 100)


def getSystemTimeStr():
    global _systime
    return formatTime(_systime)


def sgn(x):
    if x < 0:
        return -1
    elif x == 0:
        return 0
    else:
        return 1


def interpretDelayfunc(obj, rand_seed, delayfunc):
    global RANDOMIZED_KEY
    if delayfunc[0] == "deterministic":
        return delayfunc[1]
    else:
        if rand_seed is None:
            seed = str(obj) + RANDOMIZED_KEY
            rand_seed = random.Random(seed)
        if delayfunc[0] == "normal":  # normal mu sigma
            return rand_seed.gauss(delayfunc[1], delayfunc[2])
        elif delayfunc[0] == "uniform":  # uniform a b
            return rand_seed.uniform(delayfunc[1], delayfunc[2])
        elif delayfunc[0] == "exponential":  # exponential lambda
            return rand_seed.expovariate(delayfunc[1])
        elif delayfunc[0] == "pareto":  # pareto alpha
            return rand_seed.paretovariate(delayfunc[1])
        elif delayfunc[0] == "weibull":  # weibull alpha beta
            return rand_seed.weibullvariate(delayfunc[1], delayfunc[2])
        else:
            print "Unsupported distribution", delayfunc
            sys.exit(-1)


def toSystemTime(tm):
    return tm * 1000000


def getSequence():
    global _seq_seed
    _seq_seed = _seq_seed + 1
    return _seq_seed


class CRouter:
    id = None  # 4 octect ip address
    asn = None  # u_int16_t AS number
    peers = None  # dictionary key: router id
    loc_rib = None  # dictionary key: prefix
    origin_rib = None
    next_idle_time = None  # the time to process the next update, guarantee procee in order
    mrai = None
    mrai_setting = None
    route_reflector = None
    rand_seed = None

    # used for distributed simulation
    # by Phil
    is_cross_server = None
    neighbor_servers = None
    remote_peers = None

    def __init__(self, a, i):
        global MRAI_PEER_BASED, RANDOMIZED_KEY
        self.id = i
        self.asn = a
        self.peers = {}  # rib_ins, rib_outs, mrai_timers
        self.loc_rib = {}
        self.origin_rib = {}
        self.next_idle_time = -1
        self.mrai = {}
        self.mrai_setting = MRAI_PEER_BASED
        self.route_reflector = False
        seed = str(self) + RANDOMIZED_KEY
        self.rand_seed = random.Random(seed)
        # used for distributed simulation
        # by Phil
        self.is_cross_server = False
        self.neighbor_servers = [0, 0, 0]
        self.remote_peers = []

    def __str__(self):
        return str(self.id) + "(" + str(self.asn) + ")"

    def setMRAI(self, pid, prefix):
        return self.setMRAIvalue(pid, prefix, self.peers[pid].mrai_timer())

    def setMRAIvalue(self, pid, prefix, value):
        if value <= 0:
            return -1
        global SHOW_DEBUG, MRAI_PEER_BASED, MRAI_PREFIX_BASED
        if self.mrai_setting == MRAI_PEER_BASED:
            if (not self.mrai.has_key(pid)) or self.mrai[pid] < _systime:  # has not been set
                self.mrai[pid] = _systime + value
                if SHOW_DEBUG:
                    print str(self), "set mrai timer for ", pid, "to", self.mrai[pid]
            return self.mrai[pid]
        else:  # MRAI_PREFIX_BASED:
            if not self.mrai.has_key(pid):
                self.mrai[pid] = {}
            if (not self.mrai[pid].has_key(prefix)) or self.mrai[pid][
                prefix] < _systime:  # if mrai has not been set yet
                self.mrai[pid][prefix] = _systime + value
                if SHOW_DEBUG:
                    print str(self), "set mrai timer for ", pid, prefix, "to", self.mrai[pid]
            return self.mrai[pid][prefix]

    def resetMRAI(self, pid, prefix):
        global MRAI_PEER_BASED, MRAI_PREFIX_BASED
        if self.mrai_setting == MRAI_PEER_BASED and self.mrai.has_key(pid):
            self.mrai[pid] = 0
        # print str(self), "set mrai timer for ", pid, "to", self.mrai[pid]
        else:  # MRAI_PREFIX_BASED:
            if self.mrai.has_key(pid) and self.mrai[pid].has_key(prefix):  # if mrai has not been set yet
                self.mrai[pid][prefix] = 0
            # print str(self), "set mrai timer for ", pid, prefix, "to", self.mrai[pid]

    def mraiExpires(self, pid, prefix):
        global MRAI_PEER_BASED, MRAI_PREFIX_BASED
        if self.mrai_setting == MRAI_PEER_BASED:
            if (not self.mrai.has_key(pid)) or self.mrai[pid] < _systime:
                return -1  # expires
            else:
                return self.mrai[pid]  # return the expected expiring time
        elif self.mrai_setting == MRAI_PREFIX_BASED:
            if (not self.mrai.has_key(pid)) or (not self.mrai[pid].has_key(prefix)) or self.mrai[pid][
                prefix] < _systime:
                return -1  # expired
            else:
                return self.mrai[pid][prefix]  # return the expected expiring time
        else:
            print "Invalid mrai setting"
            sys.exit(-1)

    def getPeerLink(self, pid):
        return getRouterLink(self.id, pid)

    def importFilter(self, pid, prefix, path):
        global _route_map_list
        # print "check importFilter", self, pid, prefix, path
        if self.getPeerLink(pid).ibgp_ebgp() == EBGP_SESSION:
            # loop detection
            if self.asn in path.aspath:
                return False
        maps = self.peers[pid].getRouteMapIn()
        for mapname in maps:
            map = _route_map_list[mapname]
            if len(map.action) == 0 and (
                ((not map.permit) and map.isMatch(prefix, path)) or (map.permit and (not map.isMatch(prefix, path)))):
                return False
        return True

    def importAction(self, pid, prefix, path):
        global _route_map_list, default_local_preference, backup_routing, default_backup_weight_internal, default_backup_weight_external, default_backup_weigth_internal_client, ALTERNATIVE_BACKUP, _router_list
        newpath = CPath()
        newpath.copy(path)
        if self.getPeerLink(pid).ibgp_ebgp() == EBGP_SESSION:
            newpath.weight = default_weight
            newpath.nexthop = self.peers[pid].id
            newpath.local_pref = default_local_preference
            newpath.igp_cost = 0
            if len(newpath.aspath) == 0 or newpath.aspath[0] != _router_list[pid].asn:
                newpath.aspath.insert(0, _router_list[pid].asn)
        else:
            newpath.igp_cost = self.getPeerLink(pid).cost + newpath.igp_cost
            newpath.weight = default_weight
        newpath.src_pid = pid
        maps = self.peers[pid].getRouteMapIn()
        for mapname in maps:
            map = _route_map_list[mapname]
            if map.permit and len(map.action) > 0 and map.isMatch(prefix, newpath):
                newpath = map.performAction(newpath)
        if backup_routing and newpath.alternative == ALTERNATIVE_BACKUP:
            if self.getPeerLink(pid).ibgp_ebgp() == EBGP_SESSION:
                newpath.weight = default_backup_weight_external
            # print str(newpath)
            else:
                if self.peers[pid].route_reflector_client:
                    newpath.weight = default_backup_weight_internal_client
                else:
                    newpath.weight = default_backup_weight_internal
                # print str(newpath)
        return newpath

    def exportFilter(self, pid, prefix, path):
        global _router_list, ssld, _route_map_list, SHOW_DEBUG
        if path.src_pid == pid:
            if SHOW_DEBUG:
                print "source loop detection fail!"
            return False
        if self.getPeerLink(pid).ibgp_ebgp() == EBGP_SESSION:  # ebgp
            # poison reverse
            if len(path.aspath) > 0 and _router_list[pid].asn == path.aspath[0]:
                if SHOW_DEBUG:
                    print "AS path loop detection fail!"
                return False
            # send-side loop detection, SSLD
            if ssld and _router_list[pid].asn in path.aspath:
                if SHOW_DEBUG:
                    print "AS path ssld loop detection fail!"
                return False
        else:  # ibgp
            if (path.src_pid is not None) and self.getPeerLink(path.src_pid).ibgp_ebgp() == IBGP_SESSION:
                # if SHOW_DEBUG:
                #	print "IBGPXXXXX:", str(self), path.src_pid, self.peers[path.src_pid].route_reflector_client, pid, self.peers[pid].route_reflector_client
                if (not self.route_reflector) or ((not self.peers[path.src_pid].route_reflector_client) and (
                not self.peers[pid].route_reflector_client)):
                    if SHOW_DEBUG:
                        print "IBGPXXXXX:", str(self), path.src_pid, self.peers[
                            path.src_pid].route_reflector_client, pid, self.peers[
                            pid].route_reflector_client, "ibgp route-refelctor checking fail!"
                    return False
                # print "PASSXXXXXX"
        maps = self.peers[pid].getRouteMapOut()
        for mapname in maps:
            map = _route_map_list[mapname]
            if len(map.action) == 0 and (
                ((not map.permit) and map.isMatch(prefix, path)) or (map.permit and (not map.isMatch(prefix, path)))):
                if SHOW_DEBUG:
                    print "route map fail!"
                return False
        return True

    def exportAction(self, pid, prefix, path):
        global _route_map_list, EPIC, _systime
        newpath = CPath()
        newpath.copy(path)
        if self.peers[pid].link.ibgp_ebgp() == EBGP_SESSION:
            newpath.local_pref = -1
            newpath.aspath.insert(0, self.asn)  # append paths
            newpath.igp_cost = -1
            if EPIC:
                if newpath.fesnpath is None:
                    newpath.fesnpath = []
                newpath.fesnpath.insert(0, self.peers[pid].getFesnNumber(prefix))
        maps = self.peers[pid].getRouteMapOut()
        for mapname in maps:
            map = _route_map_list[mapname]
            if map.permit and len(map.action) > 0 and map.isMatch(prefix, newpath):
                path = map.performAction(newpath)
        return newpath

    def comparePath(self, path1, path2):
        return path1.compareTo(path2)

    def pathSelection(self, prefix):
        global backup_routing, ALTERNATIVE_BACKUP
        inpaths = []
        if self.origin_rib.has_key(prefix):
            inpaths.append(self.origin_rib[prefix])
        else:
            for peer in self.peers.values():
                if peer.rib_in.has_key(prefix):
                    for path in peer.rib_in[prefix]:
                        inpaths.append(path)
            inpaths.sort(self.comparePath)
            # used for distributed simulation by Phil
            # for [peer, server] in self.remote_peers:


        if backup_routing and self.loc_rib.has_key(prefix) and len(self.loc_rib[prefix]) > 0 and self.loc_rib[prefix][
            0].alternative == ALTERNATIVE_BACKUP and len(inpaths) > 0 and inpaths[
            0].alternative == ALTERNATIVE_BACKUP:  # and self.loc_rib[prefix][0].weight == inpaths[0].weight:
            for p in inpaths:
                if p.compareTo2(self.loc_rib[prefix][0]) == 0:
                    return [False, 0]
        if not self.loc_rib.has_key(prefix):
            self.loc_rib[prefix] = []
        change = False
        trend = 0
        if MAX_PATH_NUMBER > 1:
            pathnum = MAX_PATH_NUMBER
            if pathnum > len(inpaths):
                pathnum = len(inpaths)
            i = 0
            while i < pathnum or i < len(self.loc_rib[prefix]):
                if i < pathnum and i < len(self.loc_rib[prefix]):
                    # print pathnum, len(self.loc_rib[prefix]), str(inpaths[i]), str(self.loc_rib[prefix][i])
                    if inpaths[i].compareTo2(self.loc_rib[prefix][i]) != 0:
                        self.loc_rib[prefix][i] = inpaths[i]
                        change = True
                        trend = self.loc_rib[prefix][i].compareTo(inpaths[i])
                    i = i + 1
                elif i >= pathnum and i < len(self.loc_rib[prefix]):
                    self.loc_rib[prefix].pop(i)
                    change = True
                    trend = -1
                elif i < pathnum and i >= len(self.loc_rib[prefix]):
                    self.loc_rib[prefix].append(inpaths[i])
                    i = i + 1
                    change = True
                    trend = 1
        else:
            if len(self.loc_rib[prefix]) == 0 and len(inpaths) > 0:
                self.loc_rib[prefix].append(inpaths[0])
                trend = 1
                change = True
            elif len(self.loc_rib[prefix]) > 0 and len(inpaths) == 0:
                del self.loc_rib[prefix][0]
                trend = -1
                change = True
            elif len(self.loc_rib[prefix]) > 0 and len(inpaths) > 0 and self.loc_rib[prefix][0].compareTo2(
                    inpaths[0]) != 0:
                trend = self.loc_rib[prefix][0].compareTo(inpaths[0])
                del self.loc_rib[prefix][0]
                self.loc_rib[prefix].append(inpaths[0])
                change = True
        return [change, trend]

    def receive(self, pid, update):
        global ALTERNATIVE_EXIST, EPIC
        if self.getPeerLink(pid).status == LINK_DOWN:
            return
        if EPIC:
            keepFesn = False
            if update.fesn is not None:
                for peer in self.peers.values():
                    if peer.rib_in.has_key(update.prefix):
                        i = 0
                        while i < len(peer.rib_in[update.prefix]):
                            if self.fesnMatch(peer.rib_in[update.prefix][i], update.fesn):
                                keepFesn = True
                                del peer.rib_in[update.prefix][i]
                            else:
                                i = i + 1
            if keepFesn:
                for peer in self.peers.values():
                    if pid != peer.id:
                        peer.addFesn(update.prefix, update.fesn)
        tmppaths = []
        for path in update.paths:
            if self.importFilter(pid, update.prefix, path):
                tmppaths.append(self.importAction(pid, update.prefix, path))
        if backup_routing and len(tmppaths) == 0 and len(update.paths) > 0 and update.paths[
            0].alternative == ALTERNATIVE_EXIST:
            alterpath = CPath()
            alterpath.local_pref = default_local_preference
            alterpath.next_hop = pid
            alterpath.src_pid = pid
            alterpath.alternative = ALTERNATIVE_BACKUP
            alterpath.index = 0
            tmppaths.append(self.importAction(pid, update.prefix, alterpath))
        self.peers[pid].rib_in[update.prefix] = tmppaths
        # self.update(update.prefix)
        _event_Scheduler.add(CEvent(self.getIdelTime(), [self.id, update.prefix], EVENT_UPDATE))

    def fesnMatch(self, path, fesn):
        i = 0
        while i < len(path.aspath):
            if i - 1 < 0:
                recv_asn = self.asn
            else:
                recv_asn = path.aspath[i - 1]
            if recv_asn == fesn[0] and path.aspath[i] == fesn[1] and path.fesnpath[i] == fesn[2]:
                return True
            i = i + 1
        return False

    def peerDown(self, pid):
        global EPIC, _router_list
        prefixlist = self.peers[pid].rib_in.keys()
        self.peers[pid].clear()
        for p in prefixlist:
            if self.loc_rib.has_key(p) and len(self.loc_rib[p]) > 0 and self.loc_rib[p][0].src_pid is not None and \
                            self.loc_rib[p][0].src_pid == pid:
                if EPIC:
                    for peer in self.peers.values():
                        if peer.id != pid:
                            if self.peers[pid].link.ibgp_ebgp() == EBGP_SESSION:
                                fesn = [self.asn, self.loc_rib[p][0].aspath[0], self.loc_rib[p][0].fesnpath[0]]
                                peer.addFesn(p, fesn)
                            else:
                                if peer.link.ibgp_ebgp() == EBGP_SESSION and peer.out_rib.has_key(p) and len(
                                        peer.out_rib[p]) > 0:
                                    fesn = [_router_list[peer.id].asn, self.asn, peer.out_rib[p][0].fesnList[0]]
                                    peer.removeFesnNumber(p)
                                    peer.addFesn(p, fesn)
                self.update(p)

    def peerUp(self, pid):
        # print "peerUp", str(self), pid
        if self.mrai_setting == MRAI_PEER_BASED:
            for p in self.loc_rib.keys():
                self.peers[pid].enqueue(p)
            next_mrai = self.mraiExpires(pid, None)
            if next_mrai < 0:
                self.sendto(pid, None)
        else:
            for p in self.loc_rib.keys():
                self.peer[pid].enqueue(p)
                next_mrai = self.mraiExpires(pid, p)
                if next_mrai < 0:
                    self.sendto(pid, p)

    def update(self, prefix):
        global SHOW_UPDATE_RIBS, CHECK_LOOP, SHOW_DEBUG, GHOST_FLUSHING, GHOST_BUSTER
        [change, trend] = self.pathSelection(prefix)
        if SHOW_UPDATE_RIBS:
            self.showRib(prefix)
        if change:
            # print str(self) + " have path change for " + prefix
            # print self, change, trend, GHOST_FLUSHING, GHOST_BUSTER
            if GHOST_FLUSHING and trend < 0 and len(self.loc_rib[prefix]) > 0 and (
                not backup_routing or self.loc_rib[prefix][0].alternative != ALTERNATIVE_BACKUP):
                for pid in self.peers.keys():
                    self.ghostFlushing(pid, prefix)
                    if GHOST_BUSTER:
                        next_mrai = self.setMRAI(pid, prefix)
                        if next_mrai > 0:
                            _event_Scheduler.add(CEvent(next_mrai, [self.id, pid, prefix], EVENT_MRAI_EXPIRE_SENDTO))
            for pid in self.peers.keys():
                self.presend2peer(pid, prefix)
            # if SHOW_UPDATE_RIBS:
            #	self.showRib(prefix)
            if CHECK_LOOP:
                forwardingCheck(self, prefix)
        else:
            # print str(self) + " have no path change for " + prefix
            if backup_routing and len(self.loc_rib[prefix]) > 0 and self.loc_rib[prefix][
                0].alternative != ALTERNATIVE_BACKUP:
                # send_some = False
                for pid in self.peers.keys():
                    self.presend2peer(pid, prefix)
                # send_some = True
                # if send_some and SHOW_UPDATE_RIBS:
                #	self.showRib(prefix)

    def showRib(self, prefix):
        tmpstr = getSystemTimeStr() + " RIB: " + str(self) + "*" + prefix
        tmpstr = tmpstr + "{"
        if self.loc_rib.has_key(prefix):
            for p in self.loc_rib[prefix]:
                tmpstr = tmpstr + "*>" + str(p)
        tmpstr = tmpstr + "} "
        for p in self.peers.values():
            tmpstr = tmpstr + p.getRibInStr(prefix)
        print tmpstr

    def showAllRib(self):
        for p in self.loc_rib.keys():
            self.showRib(p)

    def presend2peer(self, pid, prefix):
        global wrate, MRAI_PEER_BASED, LINK_DOWN, EVENT_MRAI_EXPIRE_SENDTO, SHOW_DEBUG
        if self.getPeerLink(pid).status == LINK_DOWN:
            return
        self.peers[pid].enqueue(prefix)
        # print self, "enqueue", pid, prefix
        next_mrai = self.mraiExpires(pid, prefix)
        if next_mrai < 0 and always_mrai:
            if self.mrai_setting == MRAI_PEER_BASED:
                tprefix = None
            next_mrai = self.setMRAIvalue(pid, tprefix, self.peers[pid].random_mrai_wait())
            if next_mrai > 0:
                _event_Scheduler.add(CEvent(next_mrai, [self.id, pid, tprefix], EVENT_MRAI_EXPIRE_SENDTO))
            # print "Add EVENT_MRAI_EXPIRE_SENDTO ", str(self), pid, tprefix, next_mrai
        # print str(self), str(pid), str(prefix), next_mrai, wrate, self.isWithdrawal(pid, prefix)
        if next_mrai < 0 or ((not wrate) and self.isWithdrawal(pid, prefix)):
            # print "MRAI expires, send imediately ...", pid
            self.sendto(pid, prefix)
        else:  # do nothing, the scheduler will call sendto automatically when mrai timer expires
            if SHOW_DEBUG:
                print getSystemTimeStr(), self, pid, prefix, "MRAI does not expire, wait...", formatTime(
                    next_mrai - _systime)

    def announce_prefix(self, prefix):
        global default_local_preference
        npath = CPath()
        npath.nexthop = self.id
        npath.local_pref = default_local_preference
        self.origin_rib[prefix] = npath
        self.update(prefix)

    def withdraw_prefix(self, prefix):
        if self.origin_rib.has_key(prefix):
            del self.origin_rib[prefix]
            self.update(prefix)

    def sendto(self, pid, prefix):  # from out_queue
        global _event_Scheduler, SHOW_SEND_EVENTS, GHOST_BUSTER
        # print self, "sendto", pid, prefix
        sendsth = False
        peer = self.peers[pid]
        sendWithdraw = True
        if len(peer.out_queue) > 0:
            i = 0
            while i < len(peer.out_queue):
                if prefix is None:
                    if self.sendtopeer(pid, peer.out_queue[i]):
                        sendsth = True
                    if not self.isWithdrawal(pid, peer.out_queue[i]):
                        sendWithdraw = False
                    peer.out_queue.pop(i)
                elif prefix == peer.out_queue[i]:
                    if self.sendtopeer(pid, peer.out_queue[i]):
                        sendsth = True
                    if not self.isWithdrawal(pid, peer.out_queue[i]):
                        sendWithdraw = False
                    peer.out_queue.pop(i)
                    break
                else:
                    i = i + 1
        if sendsth:
            if SHOW_SEND_EVENTS:
                print getSystemTimeStr(), self, "sendto", pid, prefix
            if (not wrate) and sendWithdraw and not GHOST_BUSTER:
                return
            if self.mrai_setting == MRAI_PEER_BASED:
                prefix = None
            # self.resetMRAI(pid, prefix)
            next_mrai = self.setMRAI(pid, prefix)
            if next_mrai > 0:
                _event_Scheduler.add(CEvent(next_mrai, [self.id, pid, prefix], EVENT_MRAI_EXPIRE_SENDTO))
            # print "Add EVENT_MRAI_EXPIRE_SENDTO ", str(self), pid, prefix, next_mrai
            # else:
            #	self.resetMRAI(pid, prefix)
            #	print str(self) + " send nothing to " + pid

    def isWithdrawal(self, pid, prefix):
        global backup_routing, backup_route_as_withdrawal, ALTERNATIVE_BACKUP
        if len(self.loc_rib[prefix]) == 0:
            return True
        i = 0
        path = self.loc_rib[prefix][0]
        if not self.exportFilter(pid, prefix, path):
            return True
        if backup_routing and backup_route_as_withdrawal and path.alternative == ALTERNATIVE_BACKUP:
            return True
        return False

    def ghostFlushing(self, pid, prefix):
        global backup_routing, ALTERNATIVE_BACKUP
        # print self, "ghost flushing", pid, prefix
        self.peers[pid].dequeue(prefix)
        update = CUpdate(prefix)
        if backup_routing and len(self.loc_rib[prefix]) > 0 and self.loc_rib[prefix][
            0].alternative != ALTERNATIVE_BACKUP:
            has_alternative = False
            if self.loc_rib[prefix][0].alternative == ALTERNATIVE_EXIST and self.loc_rib[prefix][0].src_pid != pid:
                has_alternative = True
            if not has_alternative:
                for peer in self.peers.values():
                    if peer.id != self.loc_rib[prefix][0].src_pid and peer.rib_in.has_key(prefix) and len(peer.rib_in[
                                                                                                              prefix]) > 0:  # and (peer.rib_in[prefix][0].alternative != ALTERNATIVE_BACKUP or peer.id != pid):
                        has_alternative = self.exportFilter(pid, prefix, peer.rib_in[prefix][0])
                        if has_alternative:
                            break
            if has_alternative:
                backup_path = CPath()
                backup_path.nexthop = self.id
                backup_path.local_pref = default_local_preference
                backup_path.alternative = ALTERNATIVE_BACKUP
                backup_path = self.exportAction(pid, prefix, backup_path)
                backup_path.index = 0
                update.paths.append(backup_path)
        if self.peers[pid].rib_out.has_key(prefix) and len(self.peers[pid].rib_out[prefix]) > 0 and (
            not backup_routing or self.peers[pid].rib_out[prefix][0].alternative != ALTERNATIVE_BACKUP):
            return self.delivery(pid, prefix, update)

    def delivery(self, pid, prefix, update):
        global MAX_PATH_NUMBER
        change = False
        if self.peers[pid].rib_out.has_key(prefix) and len(update.paths) == len(self.peers[pid].rib_out[prefix]):
            if MAX_PATH_NUMBER > 1:
                i = 0
                while i < len(update.paths):
                    if update.paths[i].compareTo2(self.peers[pid].rib_out[prefix][i]) != 0:
                        change = True
                        break
                    i = i + 1
            elif len(update.paths) > 0:
                if update.paths[0].compareTo2(self.peers[pid].rib_out[prefix][0]) != 0:
                    change = True
        else:
            change = True
        if EPIC:
            if self.peers[pid].fesnList is not None and self.peers[pid].fesnList.has_key(prefix):
                update.fesn = self.peers[pid].fesnList[prefix]
                del self.peers[pid].fesnList[prefix]
        if change:
            self.peers[pid].rib_out[prefix] = update.paths
            _event_Scheduler.add(
                CEvent(self.getPeerLink(pid).next_delivery_time(self.id, update.size()), [self.id, pid, update],
                       EVENT_RECEIVE))
        return change

    def sendtopeer(self, pid, prefix):
        global _event_Scheduler, backup_routing, ALTERNATIVE_BACKUP, ALTERNATIVE_EXIST, MAX_PATH_NUMBER
        update = CUpdate(prefix)
        i = 0
        while i < len(self.loc_rib[prefix]):
            path = self.loc_rib[prefix][i]
            if self.exportFilter(pid, prefix, path):
                npath = self.exportAction(pid, prefix, path)
                npath.index = i
                update.paths.append(npath)
            i = i + 1
        # backup routing
        if backup_routing and self.loc_rib.has_key(prefix) and len(self.loc_rib[prefix]) > 0 and self.loc_rib[prefix][
            0].alternative != ALTERNATIVE_BACKUP:
            has_alternative = False
            if self.loc_rib[prefix][0].alternative == ALTERNATIVE_EXIST and self.loc_rib[prefix][0].src_pid != pid:
                has_alternative = True
            if not has_alternative:
                for peer in self.peers.values():
                    if peer.id != self.loc_rib[prefix][0].src_pid and peer.rib_in.has_key(prefix) and len(peer.rib_in[
                                                                                                              prefix]) > 0:  # and (peer.rib_in[prefix][0].alternative != ALTERNATIVE_BACKUP or peer.id != pid):
                        has_alternative = self.exportFilter(pid, prefix, peer.rib_in[prefix][0])
                        if has_alternative:
                            break
            if has_alternative:
                if len(update.paths) == 0:
                    # print self, "SEND_BACKUP to", pid, "SUCESS"
                    backup_path = CPath()
                    backup_path.nexthop = self.id
                    backup_path.local_pref = default_local_preference
                    backup_path.alternative = ALTERNATIVE_BACKUP
                    backup_path = self.exportAction(pid, prefix, backup_path)
                    backup_path.index = 0
                    update.paths.append(backup_path)
                else:
                    update.paths[0].alternative = ALTERNATIVE_EXIST
        # compare update and rib_out
        return self.delivery(pid, prefix, update)

    def processDelay(self):
        return toSystemTime(interpretDelayfunc(self, self.rand_seed, default_process_delay_func))

    def getIdelTime(self):
        if self.next_idle_time < _systime:
            self.next_idle_time = _systime
        self.next_idle_time = self.next_idle_time + self.processDelay()
        return self.next_idle_time


class CUpdate:
    prefix = None  # prefix
    paths = None  # array of CPath
    fesn = None  # forword edge sequence numbers

    def __init__(self, prefix):
        self.prefix = prefix
        self.paths = []

    def __str__(self):
        global EPIC
        tmpstr = self.prefix + "("
        if len(self.paths) > 0:
            for p in self.paths:
                tmpstr = tmpstr + str(p)
        else:
            tmpstr = tmpstr + "W"
        tmpstr = tmpstr + ")"
        if EPIC and self.fesn is not None:
            tmpstr = tmpstr + str(self.fesn)
        return tmpstr

    def size(self):
        sz = 4
        for p in self.paths:
            sz = sz + p.size()
        return sz


class CPath:
    index = None  # for single path routing, index=0 multipath routing, index=0,1,2,...
    src_pid = None

    # type = None
    weight = None
    local_pref = None
    med = None
    nexthop = None
    community = None
    alternative = None
    igp_cost = None
    aspath = None
    fesnpath = None

    def __init__(self):
        global default_local_preference, default_weight, ALTERNATIVE_NONE
        self.index = 0
        self.src_pid = None
        # self.type = ANNOUNCEMENT
        self.weight = default_weight
        self.local_pref = default_local_preference
        self.med = 0
        self.nexthop = ""
        self.igp_cost = 0
        self.community = []
        self.alternative = ALTERNATIVE_NONE
        self.aspath = []

    def size(self):
        return 4 + 4 + 4 + 4 + 4 * len(self.community) + 2 * len(self.aspath)

    def compareTo(self, path2):  # the lower is the superior
        global bgp_always_compare_med
        if self.index != path2.index:
            return sgn(self.index - path2.index)
        # if self.type != path2.type:
        #	return sgn(self.type - path2.type)
        if (
                self.alternative == ALTERNATIVE_BACKUP or path2.alternative == ALTERNATIVE_BACKUP) and self.alternative != path2.alternative:
            return self.alternative - path2.alternative
        if self.weight != path2.weight:
            return sgn(path2.weight - self.weight)
        if self.local_pref != path2.local_pref:
            return sgn(path2.local_pref - self.local_pref)
        if len(self.aspath) != len(path2.aspath):
            return sgn(len(self.aspath) - len(path2.aspath))
        if len(self.aspath) > 0 and len(path2.aspath) > 0 and (((not bgp_always_compare_med) and self.aspath[0] ==
            path2.aspath[0]) or bgp_always_compare_med) and self.med != path2.med:
            return sgn(self.med - path2.med)
        if self.igp_cost != path2.igp_cost:
            return self.igp_cost - path2.igp_cost
        if self.nexthop > path2.nexthop:
            return 1
        elif self.nexthop < path2.nexthop:
            return -1
        else:
            return 0

    def compareTo2(self, path2):
        result = self.compareTo(path2)
        if result != 0:
            return result
        return self.alternative - path2.alternative

    def copy(self, p2):
        global EPIC
        self.index = p2.index
        self.src_pid = p2.src_pid
        # self.type = p2.type
        self.weight = p2.weight
        self.local_pref = p2.local_pref
        self.med = p2.med
        self.nexthop = p2.nexthop
        self.igp_cost = p2.igp_cost
        self.community = []
        self.community.extend(p2.community)
        self.aspath = []
        self.aspath.extend(p2.aspath)
        self.alternative = p2.alternative
        if EPIC:
            if p2.fesnpath is not None:
                self.fesnpath = []
                self.fesnpath.extend(p2.fesnpath)

    def __str__(self):
        tmpstr = str(self.index) + "F" + str(self.src_pid) + "L" + str(self.local_pref) + str(self.aspath) + "M" + str(
            self.med) + "N" + str(self.nexthop) + "C" + str(self.igp_cost) + str(self.community) + "W" + str(
            self.weight) + "A" + str(self.alternative)
        if EPIC and self.fesnpath is not None:
            tmpstr = tmpstr + str(self.fesnpath)
        return tmpstr


class CPeer:
    id = None
    rib_in = None  # key: prefix, store the paths received from peer
    rib_out = None  # key: prefix, store the paths sent to peer
    out_queue = None  # store the updates hold by MRAI timer
    rand_seed = None
    mrai_base = None
    route_reflector_client = None
    route_map_in = None
    route_map_out = None
    route_map_sorted = None
    fesnList = None
    sendFesnTable = None

    def __str__(self):
        return str(self.id)

    def __init__(self, i, l):
        self.id = i
        self.link = l
        self.rib_in = {}
        self.rib_out = {}
        self.out_queue = []
        self.mrai_base = 0
        self.rand_seed = None
        self.route_map_in = None
        self.route_map_out = None
        self.route_map_sorted = False
        self.route_reflector_client = False

    def clear(self):
        global EPIC
        del self.rib_in
        self.rib_in = {}
        del self.rib_out
        self.rib_out = {}
        del self.out_queue
        self.out_queue = []
        if EPIC:
            if self.fesnList is not None:
                del self.fesnList
                self.fesnList = None
            if self.sendFesnTable is not None:
                del self.sendFesnTable
                self.sendFesnTable = None

    def addFesn(self, prefix, fesn):
        if self.fesnList is None:
            self.fesnList = {}
        self.fesnList[prefix] = fesn

    def getFesnNumber(self, prefix):
        if self.sendFesnTable is None:
            self.sendFesnTable = {}
        if not self.sendFesnTable.has_key(prefix):
            self.sendFesnTable[prefix] = _systime
        return self.sendFesnTable[prefix]

    def removeFesnNumber(self, prefix):
        if self.sendFesnTable is not None and self.sendFesnTable.has_key(prefix):
            del self.sendFesnTable[prefix]

    def mrai_timer(self):
        global MRAI_JITTER, RANDOMIZED_KEY
        if MRAI_JITTER:
            if self.rand_seed is None:
                seed = str(self) + RANDOMIZED_KEY
                self.rand_seed = random.Random(seed)
            delay = self.mrai_base * (3.0 + self.rand_seed.random() * 1.0) / 4
        else:
            delay = self.mrai_base
        return toSystemTime(delay)

    def random_mrai_wait(self):
        global RANDOMIZED_KEY
        if self.rand_seed is None:
            seed = str(self) + RANDOMIZED_KEY
            self.rand_seed = random.Random(seed)
        return toSystemTime(self.rand_seed.random() * self.mrai_base)

    def enqueue(self, prefix):
        self.dequeue(prefix)
        self.out_queue.append(prefix)

    def dequeue(self, prefix):
        if prefix in self.out_queue:
            self.out_queue.remove(prefix)

    def getRibInStr(self, prefix):
        tmpstr = "#" + self.id
        if self.rib_in.has_key(prefix):
            for p in self.rib_in[prefix]:
                tmpstr = tmpstr + "(" + str(p)
        return tmpstr

    def sortRouteMap(self):
        if self.route_map_out is not None:
            self.route_map_out.sort(cmpRouteMap)
        if self.route_map_in is not None:
            self.route_map_in.sort(cmpRouteMap)
        self.route_map_sorted = True

    def getRouteMapOut(self):
        if self.route_map_out is not None:
            if not self.route_map_sorted:
                self.sortRouteMap()
            return self.route_map_out
        else:
            return []

    def getRouteMapIn(self):
        if self.route_map_in is not None:
            if not self.route_map_sorted:
                self.sortRouteMap()
            return self.route_map_in
        else:
            return []


class CLink:
    start = None  # CRouter
    end = None  # CRouter
    status = None  # LINK_UP/LINK_DOWN
    cost = None
    bandwidth = None
    # delayfunc = None
    rand_seed = None
    next_delivery_time_start = None
    next_delivery_time_end = None

    def __str__(self):
        return str(self.start) + "-" + str(self.end)

    def __init__(self, s, e):
        global default_link_delay_func, LINK_UP
        self.start = s
        self.end = e
        self.status = LINK_UP
        self.cost = 0
        self.bandwidth = 100000000  # 100MB as default
        # self.delayfunc = ["deterministic", 0.1]
        # self.delayfunc = default_link_delay_func #["uniform", 0.01, 0.1]
        self.rand_seed = None
        self.next_deliver_time_start = 0
        self.next_deliver_time_end = 0

    def next_delivery_time(self, me, size):
        if me == self.start:
            if self.next_delivery_time_start < _systime:
                self.next_delivery_time_start = _systime
            self.next_delivery_time_start = self.next_delivery_time_start + self.link_delay(size)
            return self.next_delivery_time_start
        elif me == self.end:
            if self.next_delivery_time_end < _systime:
                self.next_delivery_time_end = _systime
            self.next_delivery_time_end = self.next_delivery_time_end + self.link_delay(size)
            return self.next_delivery_time_end

    def interpretDelayfunc(self):
        global _link_delay_table
        if _link_delay_table.has_key(self):
            return interpretDelayfunc(self, self.rand_seed, _link_delay_table[self])
        else:
            return interpretDelayfunc(self, self.rand_seed, default_link_delay_func)

    def link_delay(self, size):  # queuing delay + propagation delay
        return toSystemTime(self.interpretDelayfunc() + size * 1.0 / self.bandwidth)

    def getPeer(self, me):
        if self.start == me:
            return self.end
        elif self.end == me:
            return self.start
        else:
            print "Error, wrong link"
            sys.exit(-1)

    def ibgp_ebgp(self):
        global _router_list
        if _router_list[self.start].asn == _router_list[self.end].asn:
            return IBGP_SESSION
        else:
            return EBGP_SESSION


class CRouteMap:
    name = None
    priority = None
    permit = None
    match = None
    action = None

    def __init__(self, n, pmt, pr):
        self.name = n
        if pmt == "permit":
            self.permit = True
        else:
            self.permit = False
        self.priority = pr
        self.match = []
        self.action = []

    def isMatch(self, prefix, path):
        i = 0
        while i < len(self.match):
            cond = self.match[i]
            if cond[0] == "community-list":
                if len(cond) >= 3 and cond[2] == "exact":
                    cmlist = cond[1].split(":")
                    cmlist.sort()
                    if cmlist != path.community:
                        return False
                elif cond[1] not in path.community:
                    return False
            elif cond[0] == "as-path":
                pathstr = array2str(path.aspath, "_")
                if not re.compile(cond[1]).match(pathstr):
                    return False
            elif cond[0] == "ip" and cond[1] == "address":
                if cond[2] != prefix:
                    return False
            elif cond[0] == "metric":
                if int(cond[1]) != path.med:
                    return False
            i = i + 1
        return True

    def performAction(self, path):
        i = 0
        while i < len(self.action):
            act = self.action[i]
            if act[0] == "local-preference":
                path.local_pref = int(act[1])
            elif act[0] == "community":
                if act[1] == "none":
                    path.community = []
                else:
                    if len(act) >= 3 and act[2] == "additive":
                        path.community.extend(act[1].split(":"))
                    else:
                        path.community = act[1].split(":")
                    path.community.sort()
            elif act[0] == "as-path" and act[1] == "prepend":
                j = 0
                while j < len(act) - 2:
                    path.aspath.insert(j, int(act[2 + j]))
                    j = j + 1
            elif act[0] == "metric":
                path.med = int(act[1])
            i = i + 1
        return path


class CEvent:
    seq = 0  # sequence
    time = None  # when
    param = None  # where
    type = None  # what

    def __init__(self, tm, pr, t):
        self.seq = getSequence()
        self.time = tm
        self.param = pr
        self.type = t

    def showEvent(self): # used for distributed simulation by Phil
        global SHOW_RECEIVE_EVENTS, _router_list, SHOW_DEBUG
        # used for distributed simulation by Phil
        # print "%s event occur" %self.type
        #############
        if self.type == EVENT_RECEIVE:
            [rtid, rvid, update] = self.param
            if SHOW_RECEIVE_EVENTS:
                print formatTime(self.time), str(_router_list[rvid]), "receive", str(_router_list[rtid]), update
        elif self.type == EVENT_UPDATE:
            [rtid, prefix] = self.param
        # print self.time, rtid, "update", prefix
        elif self.type == EVENT_MRAI_EXPIRE_SENDTO:
            [sdid, rvid, prefix] = self.param
            if SHOW_DEBUG:
                print formatTime(self.time), sdid, "mrai expires", rvid, prefix
        elif self.type == EVENT_LINK_DOWN:
            [rt1, rt2] = self.param
            print formatTime(self.time), "link", str(_router_list[rt1]), "-", str(_router_list[rt2]), "down"
        elif self.type == EVENT_LINK_UP:
            [rt1, rt2] = self.param
            print formatTime(self.time), "link", str(_router_list[rt1]), "-", str(_router_list[rt2]), "up"
        elif self.type == EVENT_ANNOUNCE_PREFIX:
            [rtid, prefix] = self.param
            print formatTime(self.time), "router", str(_router_list[rtid]), "announces", prefix
        elif self.type == EVENT_WITHDRAW_PREFIX:
            [rtid, prefix] = self.param
            print formatTime(self.time), "router", str(_router_list[rtid]), "withdraws", prefix
        elif self.type == EVENT_TERMINATE:
            print formatTime(self.time), "simulation terminates"
        else:
            print formatTime(self.time), "unknown event ..."

    def process(self): # used for distributed simulation by Phil
        global _router_list
        self.showEvent()
        if self.type == EVENT_RECEIVE:
            [rtid, rvid, update] = self.param
            _router_list[rvid].receive(rtid, update)
        elif self.type == EVENT_UPDATE:
            [rtid, prefix] = self.param
            _router_list[rtid].update(prefix)
        elif self.type == EVENT_MRAI_EXPIRE_SENDTO:
            [sdid, rvid, prefix] = self.param
            _router_list[sdid].resetMRAI(rvid, prefix)
            _router_list[sdid].sendto(rvid, prefix)
        elif self.type == EVENT_LINK_DOWN:
            [rt1, rt2] = self.param
            lk = getRouterLink(rt1, rt2)
            lk.status = LINK_DOWN
            _router_list[rt1].peerDown(rt2)
            _router_list[rt2].peerDown(rt1)
        elif self.type == EVENT_LINK_UP:
            [rt1, rt2] = self.param
            lk = getRouterLink(rt1, rt2)
            lk.status = LINK_UP
            _router_list[rt1].peerUp(rt2)
            _router_list[rt2].peerUp(rt1)
        elif self.type == EVENT_ANNOUNCE_PREFIX:
            [rtid, prefix] = self.param
            _router_list[rtid].announce_prefix(prefix)
        elif self.type == EVENT_WITHDRAW_PREFIX:
            [rtid, prefix] = self.param
            _router_list[rtid].withdraw_prefix(prefix)
        elif self.type == EVENT_TERMINATE:
            return -1
        return 0

    def __cmp__(self, o):
        if self.time != o.time:
            return self.time - o.time
        return self.seq - o.seq


class COrderedList:
    data = []

    def __init__(self):
        self.data = []

    def add(self, o):
        start = 0
        end = len(self.data) - 1
        while start <= end:
            j = (start + end) / 2
            if "__cmp__" in dir(o):
                result = o.__cmp__(self.data[j])
                if result == 0:
                    return
                elif result > 0:
                    start = j + 1
                else:
                    end = j - 1
            else:
                if o == self.data[j]:
                    return
                elif o > self.data[j]:
                    start = j + 1
                else:
                    end = j - 1
        self.data.insert(start, o)

    def __getitem__(self, idx):
        return self.data[idx]

    def __len__(self):
        return len(self.data)

    def pop(self, idx):
        return self.data.pop(idx)


_router_list = {}
_router_graph = {}
_route_map_list = {}


def getRouterLink(id1, id2):
    global _router_graph
    if id1 > id2:
        rt1 = id1
        rt2 = id2
    else:
        rt2 = id1
        rt1 = id2
    if not _router_graph.has_key(rt1):
        _router_graph[rt1] = {}
    if not _router_graph[rt1].has_key(rt2):
        lk = CLink(rt1, rt2)
        _router_graph[rt1][rt2] = lk
    return _router_graph[rt1][rt2]


def array2str(path, sep):
    if len(path) == 0:
        return ""
    else:
        tmpstr = str(path[0])
        for i in range(1, len(path)):
            tmpstr = tmpstr + sep + str(path[i])
        return tmpstr


def cmpRouteMap(rm1, rm2):
    global _route_map_list
    return _route_map_list[rm1].priority - _route_map_list[rm2].priority


###################LOOP DETECTION###loop detection###Loop Detection################

LOOPCHECK_LOOP = -2
LOOPCHECK_FAILURE = -1
LOOPCHECK_SUCESS = 0


def looptype(t):
    global LOOPCHECK_FAILURE, LOOPCHECK_SUCESS, LOOPCHECK_LOOP
    if t == LOOPCHECK_FAILURE:
        return "FAIL"
    elif t == LOOPCHECK_LOOP:
        return "LOOP"
    elif t >= LOOPCHECK_SUCESS:
        return "SUCC"
    else:
        return "UNKN"


_infect_nodes = {}


def forwardingCheck(rt, prefix):
    global LOOPCHECK_FAILURE, LOOPCHECK_SUCESS, LOOPCHECK_LOOP, _loop_list
    path = [rt.id]
    result = LOOPCHECK_FAILURE  # blackhole
    while rt.loc_rib.has_key(prefix) and len(rt.loc_rib[prefix]) > 0:
        if rt.loc_rib[prefix][0].src_pid == None:
            result = LOOPCHECK_SUCESS  # sucess
            break
        rt = _router_list[rt.loc_rib[prefix][0].src_pid]
        path.append(rt.id)
        if rt.id in path[:-1]:
            del path[-1]
            result = LOOPCHECK_LOOP
            break
    # print getSystemTimeStr() + " " + looptype(result) + " " + array2str(path, "-")
    distance = {}
    if result == LOOPCHECK_SUCESS:
        i = 0
        while i < len(path):
            distance[path[i]] = len(path) - i
            i = i + 1
    else:
        for rt in path:
            distance[rt] = result
    queue = path
    while len(queue) > 0:
        rid = queue.pop(0)
        for pid in _router_list[rid].peers.keys():
            if not distance.has_key(pid):
                peer = _router_list[pid]
                if peer.loc_rib.has_key(prefix) and len(peer.loc_rib[prefix]) > 0 and peer.loc_rib[prefix][
                    0].src_pid is not None and peer.loc_rib[prefix][0].src_pid == rid:
                    queue.append(pid)
                    if result >= LOOPCHECK_SUCESS:
                        distance[pid] = distance[rid] + 1
                    else:
                        distance[pid] = result
    for node in distance.keys():
        addInfectNode(node, distance[node])


def addInfectNode(node, result):
    global _infect_nodes
    if not _infect_nodes.has_key(node):
        _infect_nodes[node] = [_systime, result]
    else:
        if _infect_nodes[node][1] != result:
            removeInfectNode(node, result)
            _infect_nodes[node] = [_systime, result]


def removeInfectNode(node, result):
    global _infect_nodes, _router_list
    if _infect_nodes.has_key(node):
        print "FCK:", formatTime(_systime), looptype(result), result, "<<", formatTime(
            _infect_nodes[node][0]), looptype(_infect_nodes[node][1]), _infect_nodes[node][1], formatTime(
            _systime - _infect_nodes[node][0]), _router_list[node]
        del _infect_nodes[node]


###################################################################################
def splitstr(line, pat):
    ele = []
    i = 0
    tmpstr = ""
    while i <= len(line):
        if i < len(line) and line[i] != pat:
            tmpstr = tmpstr + line[i]
        else:
            if tmpstr != "":
                ele.append(tmpstr.lower())
                tmpstr = ""
        i = i + 1
    return ele


def readnextcmd(fh):
    try:
        line = fh.readline()
        while len(line) > 0 and (line[0] == '!' or len(splitstr(line[:-1], ' ')) == 0):
            line = fh.readline()
        return splitstr(line[:-1], ' ')
    except:
        print "Exception: ", sys.exc_info()[0]
        raise


def interpretBandwidth(line):
    if line[-1] == 'M' or line[-1] == 'm':
        return float(line[:-1]) * 1000000
    elif line[-1] == 'K' or line[-1] == 'k':
        return float(line[:-1]) * 1000
    elif line[-1] == 'G' or line[-1] == 'g':
        return float(line[:-1]) * 1000000000
    else:
        return float(line)


def interpretDelay(param):
    if param[0] not in ["deterministic", "normal", "uniform", "exponential", "pareto", "weibull"]:
        print "Distribution", param[0], "in", param, "is not supported!"
        sys.exit(-1)
    tmparray = [param[0]]
    for i in range(1, len(param)):
        tmparray.append(float(param[i]))
    return tmparray


def readConfig(filename):
    global SHOW_UPDATE_RIBS, SHOW_RECEIVE_EVENTS, SHOW_FINAL_RIBS, wrate, always_mrai, ssld, bgp_always_compare_med, MRAI_JITTER, MAX_PATH_NUMBER, backup_routing, CHECK_LOOP, backup_route_as_withdrawal, SHOW_DEBUG, RANDOMIZED_KEY, GHOST_BUSTER, GHOST_FLUSHING, SHOW_SEND_EVENTS, default_link_delay_func, default_process_delay_func, _link_delay_table, EPIC
    try:
        f = open(filename, "r")
        cmd = readnextcmd(f)
        curRT = None
        curNB = None
        curMap = None
        while len(cmd) > 0:
            # print cmd
            if cmd[0] == "router" and cmd[1] == "bgp":
                asn = int(cmd[2])
                cmd = readnextcmd(f)
                if cmd[0] == "bgp" and cmd[1] == "router-id":
                    id = cmd[2]
                    curRT = CRouter(asn, id)
                    _router_list[id] = curRT
                else:
                    print "Error, router bgp <asn> should be followed by bgp router-id <id>"
                    sys.exit(-1)
            elif cmd[0] == "bgp":
                if cmd[1] == "cluster-id":
                    curRT.route_reflector = True
                # print "router", str(curRT), curRT.route_reflector
                elif cmd[1] == "prefix-based-timer":
                    curRT.mrai_setting = MRAI_PREFIX_BASED
                else:
                    print "unknown bgp configuration", cmd[1], "in", cmd
                    sys.exit(-1)
            elif cmd[0] == "neighbor":
                peerid = cmd[1]
                if not curRT.peers.has_key(peerid):
                    link = getRouterLink(curRT.id, peerid)
                    curNB = CPeer(peerid, link)
                    if not (len(cmd) == 5 and cmd[2] == "remote-as"): # used for distributed simulation by Phil
                        curRT.peers[peerid] = curNB
                if cmd[2] == "route-reflector-client":
                    curNB.route_reflector_client = True
                elif cmd[2] == "route-map":
                    if cmd[4] == "in":
                        if curNB.route_map_in is None:
                            curNB.route_map_in = []
                        curNB.route_map_in.append(filename + cmd[3])
                    elif cmd[4] == "out":
                        if curNB.route_map_out is None:
                            curNB.route_map_out = []
                        curNB.route_map_out.append(filename + cmd[3])
                elif cmd[2] == "advertisement-interval":  # in seconds
                    curNB.mrai_base = float(cmd[3])
                elif cmd[2] == "remote-as":
                    x = 1  # do nothing
                    # used for distributed simualation
                    # by Phil
                    if len(cmd) == 5:
                        curRT.is_cross_server = True
                        curRT.neighbor_servers[int(cmd[4]) - 1] = 1
                        curRT.remote_peers.append([peerid, cmd[4]])
                else:
                    print "unknown neighbor configuration", cmd[2], "in", cmd
                    sys.exit(-1)
            # route-map <name> permit/deny priority
            elif cmd[0] == "route-map":
                if len(cmd) >= 4:
                    pr = int(cmd[3])
                else:
                    pr = 10
                curMap = CRouteMap(filename + cmd[1], cmd[2], pr)
                _route_map_list[filename + cmd[1]] = curMap
            elif cmd[0] == "set":
                curMap.action.append(cmd[1:])
            elif cmd[0] == "match":
                curMap.match.append(cmd[1:])
            elif cmd[0] == "link":
                lk = getRouterLink(cmd[1], cmd[2])
                if cmd[3] == "cost":
                    lk.cost = int(cmd[4])
                elif cmd[3] == "bandwidth":
                    lk.bandwidth = interpretBandwidth(cmd[4])
                elif cmd[3] == "delay":
                    _link_delay_table[lk] = interpretDelay(cmd[4:])
                else:
                    print "unknown link configuration", cmd[3], "in", cmd
                    sys.exit(-1)
            elif cmd[0] == "event":
                if cmd[1] == "announce-prefix":  # event announce-prefix x.x.x.x x.x.x.x sec
                    _event_Scheduler.add(CEvent(toSystemTime(float(cmd[4])), [cmd[2], cmd[3]], EVENT_ANNOUNCE_PREFIX))
                elif cmd[1] == "withdraw-prefix":  # event withdraw-prefix x.x.x.x x.x.x.x sec
                    _event_Scheduler.add(CEvent(toSystemTime(float(cmd[4])), [cmd[2], cmd[3]], EVENT_WITHDRAW_PREFIX))
                elif cmd[1] == "link-down":  # event link-down x.x.x.x x.x.x.x sec
                    _event_Scheduler.add(CEvent(toSystemTime(float(cmd[4])), [cmd[2], cmd[3]], EVENT_LINK_DOWN))
                elif cmd[1] == "link-up":  # event link-up x.x.x.x x.x.x.x sec
                    _event_Scheduler.add(CEvent(toSystemTime(float(cmd[4])), [cmd[2], cmd[3]], EVENT_LINK_UP))
                elif cmd[1] == "terminate":
                    _event_Scheduler.add(CEvent(toSystemTime(float(cmd[2])), [], EVENT_TERMINATE))
                else:
                    print "unknown event", cmd[1], "in", cmd
                    sys.exit(-1)
            elif cmd[0] == "debug":
                if cmd[1] == "show-update-ribs":
                    SHOW_UPDATE_RIBS = True
                elif cmd[1] == "show-receive-events":
                    SHOW_RECEIVE_EVENTS = True
                elif cmd[1] == "show-final-ribs":
                    SHOW_FINAL_RIBS = True
                elif cmd[1] == "show-debug":
                    SHOW_DEBUG = True
                elif cmd[1] == "check-loop":
                    CHECK_LOOP = True
                elif cmd[1] == "show-send-events":
                    SHOW_SEND_EVENTS = True
                else:
                    print "unknown debug option", cmd[1], "in", cmd
                    sys.exit(-1)
            elif cmd[0] == "config":
                if cmd[1] == "number-of-best-paths":
                    MAX_PATH_NUMBER = int(cmd[2])
                    if backup_routing or GHOST_FLUSHING:
                        MAX_PATH_NUMBER = 1
                elif cmd[1] == "mrai-jitter":
                    if cmd[2] == "true":
                        MRAI_JITTER = True
                    else:
                        MRAI_JITTER = False
                elif cmd[1] == "always-compare-med":
                    bgp_always_compare_med = True
                elif cmd[1] == "withdraw-rate-limiting":
                    wrate = True
                elif cmd[1] == "sender-side-loop-detection":
                    ssld = True
                elif cmd[1] == "always-mrai":
                    always_mrai = True
                elif cmd[1] == "backup-routing":
                    backup_routing = True
                    MAX_PATH_NUMBER = 1
                elif cmd[1] == "backup-route-as-withdrawal":
                    backup_route_as_withdrawal = True
                elif cmd[1] == "randomize-key":
                    if cmd[2] == "random":
                        RANDOMIZED_KEY = str(time.time())
                    else:
                        RANDOMIZED_KEY = cmd[2]
                elif cmd[1] == "ghost-flushing":
                    GHOST_FLUSHING = True
                    MAX_PATH_NUMBER = 1
                elif cmd[1] == "ghost-buster":
                    GHOST_FLUSHING = True
                    GHOST_BUSTER = True
                    MAX_PATH_NUMBER = 1
                elif cmd[1] == "default-link-delay":
                    default_link_delay_func = interpretDelay(cmd[2:])
                elif cmd[1] == "default-process-delay":
                    default_process_delay_func = interpretDelay(cmd[2:])
                elif cmd[1] == "epic":
                    EPIC = True
                else:
                    print "unknown config option", cmd[1], "in", cmd
                    sys.exit(-1)
            else:
                print "unkown command", cmd[0], "in", cmd
                sys.exit(-1)
            cmd = readnextcmd(f)
        f.close()
    except:
        print "Exception: ", sys.exc_info()[0]
        raise

_event_Scheduler = COrderedList()

if len(sys.argv) < 2:
    print "Usage: bgpSimfull.py configfile\n"
    sys.exit(-1)

readConfig(sys.argv[1])

_systime = 0

# used for distributed simulation
# by Phil
_count = 0 # how many times the _event_Scheduler is iterated

def process_message(message):
    
def Simu_Process(pipe):
    global _systime, _event_Scheduler, _count
    while True:
        _count += 1
        while len(_event_Scheduler) > 0:
            cur_event = _event_Scheduler.pop(0)
            _systime = cur_event.time
            if cur_event.process() == -1:
                print 'cur_event process error'
                break
        if SHOW_FINAL_RIBS:
            print "-----======$$$$$$$$ FINISH {n} times $$$$$$$$$=======------".format(n=_count)
            for rt in _router_list.values():
                rt.showAllRib()
        pipe_data = pipe.recv()
        while not pipe_data == 'EOF':
            pickle.loads(pipe_data)
            pipe_data = pipe.recv()


s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('', 51234))
s.listen(1)
print 'listening...'

def handle(sock, addr, pipe):
    print 'Accept new connection from %s:%s...' % addr
    pipe.send("test")
    while True:
        sock_data = sock.recv(1024)
        if sock_data:
            print 'sock_data received is', sock_data
            pipe.send(sock_data)
        pipe_data = pipe.recv()
        if pipe_data:
            print 'pipe_data received is', pipe_data
            sock.send(str(pipe_data))

while True:
    sock, addr = s.accept()
    pipe = multiprocessing.Pipe()
    p_simu = multiprocessing.Process(target=Simu_Process, args=(pipe[0], ))
    t = threading.Thread(target=handle, args=(sock, addr, pipe[1]))
    p_simu.start()
    t.start()

######################################


# if CHECK_LOOP:
#     nodes = _infect_nodes.keys()
#     for node in nodes:
#         removeInfectNode(node, LOOPCHECK_FAILURE)
#

