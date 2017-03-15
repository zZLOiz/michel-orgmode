#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import datetime

class PartTree:
    def __init__(self, parent, task):
        self.task = task
        self.parent = parent
        self.repeated = False
        
        self.hash_sum = 0
        if self.task.title:
            for char in self.task.title:
                self.hash_sum += ord(char)

    def is_title_equal(self, another):
        return self.task.title == another.task.title

    def is_fully_equal(self, another):
        return\
            self.task.title == another.task.title and\
            self.task.schedule_time == another.task.schedule_time

    def __str__(self):
        return "[ {0} {1} {{{2}}}, p: {3} ]".format(
            self.task.title,
            self.hash_sum,
            self.task.schedule_time,
            self.parent.task.title if self.parent else None)

    def __repr__(self):
        return str(self)

class MergeEntry:
    def __init__(self, org, remote, base = None):
        self.org = org
        self.remote = remote
        self.base = base

    def __str__(self):
        return "org:{0} remote:{1} base:{2}".format(self.org, self.remote, self.base)

    def __repr__(self):
        return str(self)

def _disassemble_tree(tree, disassemblies):
    def _disassemble(tree, parent, groups):
        current = PartTree(parent, tree)

        prior_task = groups.get(tree.title, None)
        if prior_task is None:
            groups[tree.title] = current
        else:
            prior_task.repeated = True
            current.repeated = True
    
        disassemblies.append(current)
        for i in range(len(tree)):
            _disassemble(tree[i], current, groups)
        
    _disassemble(tree, None, {})
    disassemblies.sort(key=lambda node: node.hash_sum)

def merge_attr(mapping, attr_name, merge_func, changes_list):
    if getattr(mapping.org, attr_name) != getattr(mapping.remote, attr_name):
        setattr(mapping.org, attr_name, merge_func(mapping))
            
    if getattr(mapping.remote, attr_name) != getattr(mapping.org, attr_name):
        setattr(mapping.remote, attr_name, getattr(mapping.org, attr_name))
        changes_list.append(attr_name)

def copy_attr(task_dst, task_src):
    for attr_name in ["notes", "todo", "completed", "closed_time", "schedule_time"]:
        setattr(task_dst, attr_name, getattr(task_src, attr_name))

def _merge_repeated_tasks(mapped_tasks, tasks_org, tasks_remote, index_org, index_remote):
    def _extract_group(tasks, index):
        group = []
        reference_task = tasks[index]

        while index < len(tasks) and reference_task.is_title_equal(tasks[index]):
            group.append(tasks.pop(index))

        group.sort(key=lambda node: node.task.schedule_time)
        return group

    group_org = _extract_group(tasks_org, index_org)
    group_remote = _extract_group(tasks_remote, index_remote)

    while len(group_org) > 0 and len(group_remote) > 0:
        goi, gri = 0, 0
        max_delta = sys.maxsize
        merge_list = []

        while goi < len(group_org) and gri < len(group_remote):
            delta = group_org[goi].task.schedule_time.get_hash() - group_remote[gri].task.schedule_time.get_hash()
            abs_delta = abs(delta)
            
            if abs_delta < max_delta:
                max_delta = abs(delta)
                merge_list.clear()
                
            if abs_delta == max_delta:
                merge_list.append((goi, gri))

            if delta > 0:
                gri += 1
            else:
                goi += 1

        for entry in merge_list:
            mapped_tasks.append(MergeEntry(group_org[entry[0]], group_remote[entry[1]]))
            group_org[entry[0]] = None
            group_remote[entry[1]] = None

        group_org = [x for x in group_org if x is not None]
        group_remote = [x for x in group_remote if x is not None]

    for entry in group_org:
        tasks_org.insert(index_org, entry)
    for entry in group_remote:
        tasks_remote.insert(index_remote, entry)


def treemerge(tree_org, tree_remote, tree_base, conf):
    tasks_base = []
    tasks_org = []
    tasks_remote = []
    sync_plan = []

    _disassemble_tree(tree_org, tasks_org)
    _disassemble_tree(tree_remote, tasks_remote)
    if tree_base is not None:
        _disassemble_tree(tree_base, tasks_base)

    mapped_tasks = []

    # first step, exact matching
    index_remote, index_org = 0, 0
    while index_remote < len(tasks_remote):
        is_mapped = False
        index_org = 0
        
        while index_org < len(tasks_org):
            if tasks_remote[index_remote].is_title_equal(tasks_org[index_org]):
                if not tasks_org[index_org].repeated and not tasks_remote[index_remote].repeated:
                    mapped_tasks.append(MergeEntry(tasks_org.pop(index_org), tasks_remote.pop(index_remote)))
                else:
                    _merge_repeated_tasks(mapped_tasks, tasks_org, tasks_remote, index_org, index_remote)

                is_mapped = True
                break
            else:
                index_org += 1

        if not is_mapped:
            index_remote += 1

    # second step, fuzzy matching
    index_remote, index_org = 0, 0
    while index_remote < len(tasks_remote) and len(tasks_org) > 0:
        index_org = conf.select_org_task(tasks_remote[index_remote].task, (x.task for x in tasks_org))

        if index_org == 'discard':
            tasks_remote[index_remote].task.completed = True
        elif index_org != 'new':
            mapped_tasks.append(MergeEntry(tasks_org.pop(index_org), tasks_remote.pop(index_remote)))
            continue

        index_remote += 1

    # second and half step, base entry exact matching
    index_mapping, index_base = 0, 0
    while index_mapping < len(mapped_tasks):
        index_base = 0

        while index_base < len(tasks_base):
            if mapped_tasks[index_mapping].org.is_fully_equal(tasks_base[index_base]) or\
               mapped_tasks[index_mapping].remote.is_fully_equal(tasks_base[index_base]):
                mapped_tasks[index_mapping].base = tasks_base.pop(index_base)
                break
            else:
                index_base += 1

        index_mapping += 1
            

    # third step, patching org tree
    for map_entry in mapped_tasks:
        diff_notes = []
        changes_list = []

        merge_entry = MergeEntry(
            map_entry.org.task,
            map_entry.remote.task,
            map_entry.base.task if map_entry.base is not None else None)
        
        merge_attr(merge_entry, "title", lambda a: conf.merge_title(a), changes_list)
        merge_attr(merge_entry, "completed", lambda a: conf.merge_completed(a), changes_list)
        merge_attr(merge_entry, "closed_time", lambda a: conf.merge_closed_time(a), changes_list)
        merge_attr(merge_entry, "schedule_time", lambda a: conf.merge_schedule_time(a), changes_list)
        merge_attr(merge_entry, "notes", lambda a: conf.merge_notes(a), changes_list)

        if conf.is_needed(map_entry.remote.task):
            if len(changes_list) > 0:
                sync_plan.append({
                    "action": "update",
                    "changes": changes_list,
                    "item": map_entry.remote.task
                })
        else:
            if map_entry.remote.task.title is not None:
                sync_plan.append({
                    "action": "remove",
                    "item": map_entry.remote.task
                })

    # fourth step, append new items to org tree
    for i in range(len(tasks_remote)):
        new_task = tasks_remote[i]

        try:
            parent_task = next(x for x in mapped_tasks if x.remote == new_task.parent).org.task
        except StopIteration:
            parent_task = tree_org

        created_task = parent_task.add_subtask(new_task.task.title)
        copy_attr(created_task, new_task.task)

        if not conf.is_needed(new_task.task):
            sync_plan.append({
                "action": "remove",
                "item": new_task.task
            })

    # fifth step, append new items to remote tree
    for i in range(len(tasks_org)):
        new_task = tasks_org[i]

        if not conf.is_needed(new_task.task):
            continue

        try:
            parent_task = next(x for x in mapped_tasks if x.org == new_task.parent).remote.task
        except StopIteration:
            parent_task = tree_remote

        created_task = parent_task.add_subtask(new_task.task.title)
        copy_attr(created_task, new_task.task)

        sync_plan.append({
            "action": "append",
            "item": created_task
        })

    return sync_plan
