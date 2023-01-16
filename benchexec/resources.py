#resources_new.py

"""
This module contains functions for computing assignments of resources to runs.
"""

import collections
import itertools
import logging
import math
import os
import sys
from functools import cmp_to_key

import cgroups
import util

# prepping function, consider change of name
def get_cpu_cores_per_run(  
    coreLimit, num_of_threads, use_hyperthreading, my_cgroups, coreSet=None):
    hierarchy_levels = []
    try:
        # read list of available CPU cores (int)
        allCpus_list = get_cpu_list(my_cgroups, coreSet)

        # read & prepare hyper-threading information, filter superfluous entries
        siblings_of_core = get_siblings_mapping (allCpus_list)
        cleanList = []
        for core in siblings_of_core:
            if core not in cleanList:
                for sibling in siblings_of_core[core]:
                    if sibling != core:
                        cleanList.append(sibling)
        for element in cleanList:
            siblings_of_core.pop(element)
        # siblings_of_core will be added to hierarchy_levels list after sorting

        # read & prepare mapping of cores to L3 cache
        # cores_of_L3cache = 
        # hierarchy_levels.append(core_of_L3cache)
        
        # read & prepare mapping of cores to NUMA region
        cores_of_NUMA_Region = get_NUMA_mapping (allCpus_list)
        hierarchy_levels.append(cores_of_NUMA_Region)

        # read & prepare mapping of cores to group
        # core_of_group =
        #hierarchy_levels.append(core_of_group)

        # read & prepare mapping of cores to CPU/physical package/socket?
        cores_of_package = get_package_mapping (allCpus_list)
        hierarchy_levels.append(cores_of_package)
    
    except ValueError as e:
        sys.exit(f"Could not read CPU information from kernel: {e}")
    
    # generate sorted list of dicts in accordance with their hierarchy
    def compare_hierarchy(dict1, dict2):
        value1 = len(next(iter(dict1.values())))
        value2 = len(next(iter(dict2.values())))
        if value1 > value2:
            return 1
        if value1 < value2:
            return -1
        if value1 == value2:
            return 0

    # sort hierarchy_levels according to the dicts' corresponding unit sizes
    hierarchy_levels.sort(key = cmp_to_key(compare_hierarchy))  #hierarchy_level = [dict1, dict2, dict3]
    # add siblings_of_core at the beginning of the list
    hierarchy_levels.insert(0, siblings_of_core)

    # create v_cores
    allCpus = {}
    for cpu_nr in allCpus_list:
        allCpus.update({cpu_nr: v_core(cpu_nr,[])})

    for level in hierarchy_levels:                          # hierarchy_levels = [dict1, dict2, dict3]
        for key in level:
            for core in level[key]:
                allCpus[core].memory_regions.append(key)    # memory_regions = [key1, key2, key3]


    # call the actual assignment function
    return assignmentAlgorithm (
        coreLimit, 
        num_of_threads, 
        use_hyperthreading, 
        allCpus,
        siblings_of_core,
        hierarchy_levels
    )

# define class v_core to generate core objects
class v_core: 
    #def __init__(self, id, siblings=None, memory_regions=None):
    def __init__(self, id, memory_regions=None):
        self.id = id
        #self.siblings = siblings
        self.memory_regions = memory_regions
    def __str__(self):
        return str(self.id) + " " + str(self.memory_regions)

# assigns the v_cores into specific runs
def assignmentAlgorithm (
    coreLimit,              
    num_of_threads, 
    use_hyperthreading, 
    allCpus,
    siblings_of_core,
    hierarchy_levels
):
    """This method does the actual work of _get_cpu_cores_per_run
    without reading the machine architecture from the file system
    in order to be testable.
    @param coreLimit: the number of cores for each run
    @param num_of_threads: the number of parallel benchmark executions
    @param use_hyperthreading: boolean to check if no-hyperthreading method is being used
    @param allCpus: the list of all available cores
    @param siblings_of_core: mapping from each core to list of sibling cores including the core itself
    cores_of_L3cache,
    cores_of_NUMA_Region,
    core_of_group,
    cores_of_package
    """
    # First: checks whether the algorithm can & should work

    # no HT filter: delete all but one the key core from siblings_of_core 
    # delete those cores from all dicts in hierarchy_levels    
    if not use_hyperthreading:
        for core in siblings_of_core:
            no_HT_filter = []
            for sibling in siblings_of_core[core]:
                if sibling != core:
                    no_HT_filter.append(sibling)
            for virtual_core in no_HT_filter:
                siblings_of_core[core].remove(virtual_core)
                region_keys = allCpus[virtual_core].memory_regions
                i=1
                while i < len(region_keys):
                    hierarchy_levels[i][region_keys[i]].remove(virtual_core)
                    i = i+1
                allCpus.pop(virtual_core)

    # compare number of available cores to required cores per run
    coreCount = len(allCpus)
    if coreLimit > coreCount:
        sys.exit(
                f"Cannot run benchmarks with {coreLimit} CPU cores, "
                f"only {coreCount} CPU cores available."
            )
    
    # compare number of available run to overall required cores
    if coreLimit * num_of_threads > coreCount:
        sys.exit(
            f"Cannot run {num_of_threads} benchmarks in parallel "
            f"with {coreLimit} CPU cores each, only {coreCount} CPU cores available. "
            f"Please reduce the number of threads to {coreCount // coreLimit}."
        )


    # check if all HT siblings are available for benchexec
    all_cpus_set = set(allCpus.keys())
    for core, siblings in siblings_of_core.items():
        siblings_set = set(siblings)
        if not siblings_set.issubset(all_cpus_set):
            unusable_cores = siblings_set.difference(all_cpus_set)
            sys.exit(
                f"Core assignment is unsupported because siblings {unusable_cores} "
                f"of core {core} are not usable. "
                f"Please always make all virtual cores of a physical core available."
            )
    # check if all units of the same hierarchy level have the same number of cores
    for index in range(len(hierarchy_levels)): # [dict, dict, dict, ...]
        cores_per_unit = len(next(iter(hierarchy_levels[index].values())))
        print("cores_per_unit of hierarchy_level ", index," = ", cores_per_unit)
        if any(len(cores) != cores_per_unit for cores in hierarchy_levels[index].values()):
            sys.exit(
                "Asymmetric machine architecture not supported: "
                "CPUs/memory regions with different number of cores."
            )

    # ( compute some values we will need.)

    # coreLimit_rounded_up (int): recalculate # cores for each run accounting for HT
    core_size =  len(next(iter(siblings_of_core.values()))) # Wert aus hierarchy_level statt siblings_of_core?
    coreLimit_rounded_up = int(math.ceil(coreLimit / core_size) * core_size)
    assert coreLimit <= coreLimit_rounded_up < (coreLimit + core_size)


    # Choose hierarchy level for core assignment
    chosen_level = 1
    # move up in hierarchy as long as the number of cores at the current level is smaller than the coreLimit
    # if the number of cores at the current level is as big as the coreLimit: exit loop 
    while len (next(iter(hierarchy_levels[chosen_level].values()))) < coreLimit_rounded_up  and chosen_level < len (hierarchy_levels):
        chosen_level = chosen_level+1
    print("chosen_level = ",chosen_level)
    unit_size = len (next(iter(hierarchy_levels[chosen_level].values())))
    print("unit_size = ", unit_size)
    assert unit_size >= coreLimit_rounded_up

    
    # calculate runs per unit of hierarchy level i
    runs_per_unit = int(math.floor(unit_size/coreLimit_rounded_up))
    
    # compare num of units & runs per unit vs num_of_threads
    if len(hierarchy_levels[chosen_level]) * runs_per_unit < num_of_threads:
        sys.exit(
            f" .........................."
            f"Please reduce the number of threads to {len(hierarchy_levels[chosen_level]) * runs_per_unit}."
        )
    
    # calculate if sub_units have to be split to accommodate the runs_per_unit
    #sub_units_per_run = math.ceil(len(hierarchy_levels[chosen_level-1])/runs_per_unit)
    #sub_units_per_run = coreLimit/num of cores per subunit 
    
    sub_units_per_run = math.ceil(coreLimit_rounded_up/len(hierarchy_levels[chosen_level-1][0]))
    print("sub_units_per_run = ", sub_units_per_run)
    if len(hierarchy_levels[chosen_level-1]) / sub_units_per_run < num_of_threads:
        sys.exit(
            f"Cannot split memory regions between runs."
            f"Please reduce the number of threads to {sub_units_per_run * runs_per_unit}."
        )


    # Start core assignment algorithm
    result = []  
    used_cores = []
    blocked_cores = []
    active_hierarchy_level = hierarchy_levels[chosen_level]
    #i=0
    while len(result) < num_of_threads: #and i < len(active_hierarchy_level):
        
        #choose cores for assignment:
        i = len(hierarchy_levels)-1
        #start with highest dict: if length = 1 or length of values equal
        while len(hierarchy_levels[i]) == 1 \
            or not (any(len(cores) != len(next(iter(hierarchy_levels[i].values()))) for cores in hierarchy_levels[i].values())) \
                and i != 0:
            i = i-1
        spread_level = hierarchy_levels[i]
        # make a list of the core lists in spread_level(values())
        spread_level_values = list(spread_level.values())
        #choose values from key-value pair with the highest number of cores
        spread_level_values.sort(key=len, reverse=True)
        # return the memory region key of values first core at chosen_level
        print ("spread_level_values[0][0] = ",spread_level_values[0][0])
        spreading_memory_region_key = allCpus[spread_level_values[0][0]].memory_regions[chosen_level]
        # return the list of cores belonging to the spreading_memory_region_key
        active_cores = active_hierarchy_level[spreading_memory_region_key]
        
        '''for run in range(runs_per_unit):'''
        
        # Core assignment per thread:
        cores = []
        for sub_unit in range(sub_units_per_run):
            
            # read key of sub_region for first list element
            key = allCpus[active_cores[0]].memory_regions[chosen_level-1]
            
            # read list of cores of corresponding sub_region
            sub_unit_hierarchy_level = hierarchy_levels[chosen_level-1]
            sub_unit_cores = sub_unit_hierarchy_level[key]                                                     
            while len(cores) < coreLimit and sub_unit_cores:
                # read list of first core with siblings
                core_with_siblings = hierarchy_levels[0][allCpus[sub_unit_cores[0]].memory_regions[0]]  
                for core in core_with_siblings:
                    if len(cores) < coreLimit:
                        cores.append(core)             # add core&siblings to results
                    else: 
                        blocked_cores.append(core)     # add superfluous cores to blocked_cores
            
                    core_clean_up (core, allCpus, hierarchy_levels)

            while sub_unit_cores:
                core_clean_up (sub_unit_cores[0], allCpus, hierarchy_levels)
                #active_cores.remove(sub_unit_cores[0])
                #sub_unit_cores.remove(sub_unit_cores[0])
            
            # if coreLimit reached: append core to result, delete remaining cores from active_cores
            if len(cores) == coreLimit:
                result.append(cores)
                print (result)
            #i=i+1

    # cleanup: while-loop stops before running through all units: while some active_cores-lists 
    # & sub_unit_cores-lists are empty, other stay half-full or full
        
    return result

def core_clean_up (core, allCpus, hierarchy_levels):
    current_core_regions = allCpus[core].memory_regions
    for mem_index in range(len(current_core_regions)):
        region = current_core_regions[mem_index]
        hierarchy_levels[mem_index][region].remove(core)

# return list of available CPU cores
def get_cpu_list (my_cgroups, coreSet=None):
    # read list of available CPU cores
    allCpus = util.parse_int_list(my_cgroups.get_value(cgroups.CPUSET, "cpus"))

    # Filter CPU cores according to the list of identifiers provided by a user
    if coreSet:
        invalid_cores = sorted(set(coreSet).difference(set(allCpus)))
        if len(invalid_cores) > 0:
            raise ValueError(
                "The following provided CPU cores are not available: "
                + ", ".join(map(str, invalid_cores))
            )
        allCpus = [core for core in allCpus if core in coreSet]

    logging.debug("List of available CPU cores is %s.", allCpus)
    return allCpus
    raise ValueError (f"Could not read CPU information from kernel: {e}")

# returns dict of mapping cores to list of its siblings  
def get_siblings_mapping (allCpus):
    siblings_of_core = {}
    for core in allCpus:
        siblings = util.parse_int_list(
            util.read_file(
                f"/sys/devices/system/cpu/cpu{core}/topology/thread_siblings_list"
            )
        )
        siblings_of_core[core] = siblings
        logging.debug("Siblings of cores are %s.", siblings_of_core)

# returns dict of mapping NUMA region to list of cores
def get_NUMA_mapping (allCpus):
    cores_of_NUMA_region = collections.defaultdict(list)
    for core in allCpus:
        coreDir = f"/sys/devices/system/cpu/cpu{core}/"
        NUMA_regions = _get_memory_banks_listed_in_dir(coreDir)
        if NUMA_regions:
            cores_of_NUMA_region[NUMA_regions[0]].append(core)
            # adds core to value list at key [NUMA_region[0]]
        else:
            # If some cores do not have NUMA information, skip using it completely
            logging.warning(
                "Kernel does not have NUMA support. Use benchexec at your own risk."
            )
            cores_of_NUMA_region = {}
            break
    logging.debug("Memory regions of cores are %s.", cores_of_NUMA_region)
    return cores_of_NUMA_region
    raise ValueError (f"Could not read CPU information from kernel: {e}")
       
# returns dict of mapping CPU/physical package to list of cores
def get_package_mapping (allCpus):
    cores_of_package = collections.defaultdict(list) # Zuordnung CPU ID zu core ID 
    for core in allCpus:
        package = get_cpu_package_for_core(core)
        cores_of_package[package].append(core)
    logging.debug("Physical packages of cores are %s.", cores_of_package)
    return cores_of_package
    raise ValueError (f"Could not read CPU information from kernel: {e}")



def _get_memory_banks_listed_in_dir(path):
    """Get all memory banks the kernel lists in a given directory.
    Such a directory can be /sys/devices/system/node/ (contains all memory banks)
    or /sys/devices/system/cpu/cpu*/ (contains all memory banks on the same NUMA node as that core)."""
    # Such directories contain entries named "node<id>" for each memory bank
    return [int(entry[4:]) for entry in os.listdir(path) if entry.startswith("node")]


def check_memory_size(memLimit, num_of_threads, memoryAssignment, my_cgroups):
    """Check whether the desired amount of parallel benchmarks fits in the memory.
    Implemented are checks for memory limits via cgroup controller "memory" and
    memory bank restrictions via cgroup controller "cpuset",
    as well as whether the system actually has enough memory installed.
    @param memLimit: the memory limit in bytes per run
    @param num_of_threads: the number of parallel benchmark executions
    @param memoryAssignment: the allocation of memory banks to runs (if not present, all banks are assigned to all runs)
    """
    try:
        # Check amount of memory allowed via cgroups.
        def check_limit(actualLimit):
            if actualLimit < memLimit:
                sys.exit(
                    f"Cgroups allow only {actualLimit} bytes of memory to be used, "
                    f"cannot execute runs with {memLimit} bytes of memory."
                )
            elif actualLimit < memLimit * num_of_threads:
                sys.exit(
                    f"Cgroups allow only {actualLimit} bytes of memory to be used, "
                    f"not enough for {num_of_threads} benchmarks with {memLimit} bytes "
                    f"each. Please reduce the number of threads."
                )

        if not os.path.isdir("/sys/devices/system/node/"):
            logging.debug(
                "System without NUMA support in Linux kernel, ignoring memory assignment."
            )
            return

        if cgroups.MEMORY in my_cgroups:
            # We use the entries hierarchical_*_limit in memory.stat and not memory.*limit_in_bytes
            # because the former may be lower if memory.use_hierarchy is enabled.
            for key, value in my_cgroups.get_key_value_pairs(cgroups.MEMORY, "stat"):
                if (
                    key == "hierarchical_memory_limit"
                    or key == "hierarchical_memsw_limit"
                ):
                    check_limit(int(value))

        # Get list of all memory banks, either from memory assignment or from system.
        if not memoryAssignment:
            if cgroups.CPUSET in my_cgroups:
                allMems = my_cgroups.read_allowed_memory_banks()
            else:
                allMems = _get_memory_banks_listed_in_dir("/sys/devices/system/node/")
            memoryAssignment = [
                allMems
            ] * num_of_threads  # "fake" memory assignment: all threads on all banks
        else:
            allMems = set(itertools.chain(*memoryAssignment))

        memSizes = {mem: _get_memory_bank_size(mem) for mem in allMems}
    except ValueError as e:
        sys.exit(f"Could not read memory information from kernel: {e}")

    # Check whether enough memory is allocatable on the assigned memory banks.
    # As the sum of the sizes of the memory banks is at most the total size of memory in the system,
    # and we do this check always even if the banks are not restricted,
    # this also checks whether the system has actually enough memory installed.
    usedMem = collections.Counter()
    for mems_of_run in memoryAssignment:
        totalSize = sum(memSizes[mem] for mem in mems_of_run)
        if totalSize < memLimit:
            sys.exit(
                f"Memory banks {mems_of_run} do not have enough memory for one run, "
                f"only {totalSize} bytes available."
            )
        usedMem[tuple(mems_of_run)] += memLimit
        if usedMem[tuple(mems_of_run)] > totalSize:
            sys.exit(
                f"Memory banks {mems_of_run} do not have enough memory for all runs, "
                f"only {totalSize} bytes available. Please reduce the number of threads."
            )


def _get_memory_bank_size(memBank):
    """Get the size of a memory bank in bytes."""
    fileName = f"/sys/devices/system/node/node{memBank}/meminfo"
    size = None
    with open(fileName) as f:
        for line in f:
            if "MemTotal" in line:
                size = line.split(":")[1].strip()
                if size[-3:] != " kB":
                    raise ValueError(
                        f'"{size}" in file {fileName} is not a memory size.'
                    )
                # kernel uses KiB but names them kB, convert to Byte
                size = int(size[:-3]) * 1024
                logging.debug("Memory bank %s has size %s bytes.", memBank, size)
                return size
    raise ValueError(f"Failed to read total memory from {fileName}.")


def get_cpu_package_for_core(core):
    """Get the number of the physical package (socket) a core belongs to."""
    return int(
        util.read_file(
            f"/sys/devices/system/cpu/cpu{core}/topology/physical_package_id"
        )
    )


def get_cores_of_same_package_as(core):
    return util.parse_int_list(
        util.read_file(f"/sys/devices/system/cpu/cpu{core}/topology/core_siblings_list")
    )