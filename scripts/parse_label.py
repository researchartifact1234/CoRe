from utils import *
from typing import Set, List, Dict, Tuple, Optional, Sequence
from collections import defaultdict, deque
import re
import argparse
import random
from ScanResults import condition_range
from collections import deque

CONTROLDEP = "controldep"
DATADEP = "datadep"
def parse_single_entry(entry):
    """
    Parses a single string formatted as '(key, value)' and returns a tuple.
    
    :param entry: A string in the format '(key, value)'.
    :return: Tuple (string, int) if parsing is successful, otherwise None.
    """
    # Updated regex pattern to allow letters, numbers, and underscores in the key
    try:
        match = re.match(r'([a-zA-Z0-9_]+)\s+(\d+)', entry)
        if match:
            key = match.group(1)  # Extract the string part (variable name)
            value = int(match.group(2))  # Convert the numeric part to an integer
            return key, value
        else:
            print(f"Error: Could not parse the entry '{entry}'")
            return None
    except:
        print(f"Error: Could not parse the entry '{entry}'")
        return None


def _precision_recall_f1(pred_set: Set[Any],
                         gt_set:   Set[Any]) -> Dict[str, float]:
    """
    Compute precision / recall / F1 for two sets.
    Empty‑set edge‑cases follow the common convention:
      – if both sets are empty → precision = recall = 1.0
      – else if pred is empty   → precision = 1.0, recall = 0.0
      – else if gt   is empty   → precision = 0.0, recall = 1.0
    """
    accuracy = 1.0 if pred_set == gt_set else 0.0
    if not pred_set and not gt_set:
        precision = recall = 1.0
    elif not pred_set:
        precision, recall = 1.0, 0.0
    elif not gt_set:
        precision, recall = 0.0, 1.0
    else:
        tp        = len(pred_set & gt_set)
        precision = tp / len(pred_set)
        recall    = tp / len(gt_set)

    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall > 0 else 0.0)
    return {"precision": precision, "recall": recall, "f1": f1, "accuracy":  accuracy, "total_gt": len(gt_set), "total_pred": len(pred_set)}





def average_length(items: Sequence[Union[str, list]]) -> float:
    """
    Calculate the average length of a sequence of strings or lists.

    Args:
        items: A sequence (e.g., list or tuple) whose elements are either strings or lists.

    Returns:
        The average length of the elements as a float. Returns 0.0 for an empty input.

    Raises:
        TypeError: If any element in `items` is not a str or list.
    """
    if not items:
        return 0.0

    total = 0
    count = 0

    for idx, item in enumerate(items):
        if isinstance(item, (str, list)):
            total += len(item)
            count += 1
        else:
            raise TypeError(
                f"Element at index {idx!r} is of type {type(item).__name__}, "
                "expected str or list."
            )

    return total / count

class Variable:
    def __init__(self, varname, linenum):
        self.var = varname
        self.line = linenum
        self.data_dep: Set["Variable"] = set()
        self.control_dep: Set["Variable"] = set()
        self.equiv_to: Union[None, "Variable"] = None
        self.reset_value = True
        self.is_subscript = False

    def update_data_dep(self, dep_var:"Variable"):
        self.data_dep.add(dep_var)
    
    def update_control_dep(self, dep_var:"Variable"):
        self.control_dep.add(dep_var)

    def update_reset_value(self, reset_value:bool):
        self.reset_value = reset_value

    def set_equiv(self):
        if len(self.data_dep) == 1 and self.reset_value == False:
            self.equiv_to = list(self.data_dep)[0]

    def set_subscript(self):
        self.subscript = True

    def __repr__(self):
        return f"({self.var}, {self.line})"

    def __eq__(self, other):
        if isinstance(other, Variable) and other.var==self.var and other.line == self.line:
            return True
        return False

    def __hash__(self):
        return hash((self.var, self.line)) 

    def to_list(self) -> List:
        # return a list of [str, int]
        return [self.var, self.line]

class Program:
    def __init__(self, label_fpath:str):
        self.label_fpath:str = label_fpath   # yaml file path
        self.data = read_yaml(label_fpath)
        if not self.data:
            print(f"[Error] Fail to read from {label_fpath}")
            return
        self.vars: Dict[str, Dict[int, Variable]] = defaultdict(dict)
        self.all_vars: List[Variable] = []
        self.target_var: Variable = None
        self.other_vars: Set[Variable] = set()  # not in self.vars and self.all_vars
        self.early_return_lines: Set[int] = set()
        self.subscript: Set[Variable] = set()
        self.language: str = self.get_language()
        self.code_filepath: str = self.get_code_filepath()
        _, dataset, _, _, self.function_name, self.start_line, self.end_line = parse_filename(self.label_fpath)
        self.dataset = dataset
        self.build(self.data)
        self.set_target_var(self.data['target_var'])
        self.set_other_vars(self.data.get('other_vars', []))
        self.set_subscript_vars(self.data.get('subscript', []))
        self.set_early_return_lines(self.data.get('early_return', []))
        try:
            self.check_controldep_consistent()
        except LabelError as e:
            print(label_fpath, e.msg)
                
        unreachable_vars = self.get_unreachable_vars()
        if unreachable_vars:
            print(f"Warning: {self.label_fpath} unreachable vars: {unreachable_vars}")

        if not self.check_target_valid_datadep(self.target_var):
            print(f"Warning: {self.label_fpath} The target variable's datadep is not valid.")
        if not self.check_target_valid_controldep(self.target_var):
            print(f"Warning: {self.label_fpath} The target variable's controldep is not valid.")

        # Two adjacency maps
        self.adj_map_implicit: Dict[Variable, List[Variable]] = {}
        self.adj_map_data: Dict[Variable, List[Variable]] = {}
        self.adj_map_control: Dict[int, List[int]] = {}
        self.build_adjacency_maps()

    def get_language(self) -> str:
        """Extract language based on subfolder name."""
        return os.path.basename(os.path.dirname(os.path.dirname(self.label_fpath)))
    

    def get_code_filepath(self) -> str:
        """Find the corresponding source code file based on YAML file name."""
        base_name: str = os.path.basename(self.label_fpath).replace(".yaml", "")
        ext_map: Dict[str, str] = {"C": ".c", "Python": ".py", "Java": ".java"}
        ext: str = ext_map.get(self.language, "")
        
        # Replace 'label' with 'code' in the directory path
        label_dir = os.path.dirname(self.label_fpath)
        code_dir = label_dir.replace("/label", "/code")
    
        return os.path.join(code_dir, f"{base_name}{ext}")

    def var_exist(self, varname:str, linenum:int=-1)->bool:
        if linenum!= -1:
            return varname in self.vars and linenum in self.vars[varname]
        else:
            return varname in self.vars
             
    # TODO: set Null xxx reset to false
    def build(self, data):

        # iterate all variables, create variable objects
        for var in data['variables']:
            try:
                varname, linenum = parse_single_entry(var)
            except:
                raise LabelError(f"Invalid entry {var}")
            if self.var_exist(varname, linenum):
                print('here')
                raise LabelError(f"Duplicate entry {var}.")
        
            self.vars[varname][linenum] = Variable(varname, linenum)

        
        # update data dep and control dep
        for var, vardepdata in data['variables'].items():
            if not vardepdata:
                raise LabelError(f"Label for {var} is None.")
            varname, linenum = parse_single_entry(var)
            # update data dep
            for depvar in vardepdata[DATADEP] if vardepdata[DATADEP] else []:
                try:
                    dep_varname, dep_linenum = parse_single_entry(depvar)
                except:
                    raise LabelError(f"Invalid entry {depvar} for variable {var}")
                if not self.var_exist(dep_varname, dep_linenum):
                    raise LabelError(f"Missing entry {depvar}.")
                self.vars[varname][linenum].update_data_dep(self.vars[dep_varname][dep_linenum])
            

            # update control dep
            for depvar in vardepdata[CONTROLDEP] if vardepdata[CONTROLDEP] else []:
                dep_varname, dep_linenum = parse_single_entry(depvar)
                if not self.var_exist(dep_varname, dep_linenum):
                    raise LabelError(f"Missing entry {depvar}.")
                self.vars[varname][linenum].update_control_dep(self.vars[dep_varname][dep_linenum])
        
            self.vars[varname][linenum].update_reset_value(vardepdata.get('reset', True))
            if varname == 'Null':
                self.vars[varname][linenum].update_reset_value(False) 
            self.vars[varname][linenum].set_equiv()

        for varname_dict in self.vars.values():
            for v in varname_dict.values():
                # if v.var.lower()=="null":
                #     raise LabelError(f"Variable name {v} is NULL")
                self.all_vars.append(v)
                
    def get_unreachable_vars(self) -> Set[Variable]:
        """
        Traverse from target_var using both data and control dependencies.
        Return the set of variables in self.all_vars that are not reachable.
        """
        if not self.target_var:
            raise LabelError("Target variable is not set.")

        seen: Set[Variable] = set()
        stack: List[Variable] = [self.target_var]

        while stack:
            curr_var = stack.pop()
            if curr_var in seen:
                continue
            seen.add(curr_var)
            # Add both data and control dependencies to the stack
            neighbors = curr_var.data_dep.union(curr_var.control_dep)
            stack.extend(neighbors - seen)

        # Return variables that were not visited
        return set(self.all_vars) - seen

    def build_adjacency_maps(self):
        """
        Build two separate adjacency maps:
         - adj_map_implicit: edges = data_dep ∪ control_dep
         - adj_map_data: edges = data_dep
        """
        for v in self.all_vars:
            # For implicit flow, combine data_dep ∪ control_dep
            implicit_neighbors: List[Variable] = list(v.data_dep.union(v.control_dep))
            self.adj_map_implicit[v] = implicit_neighbors

            # For data-only flow
            data_neighbors: List[Variable] = list(v.data_dep)
            for datadep_var in v.data_dep:
                if datadep_var.reset_value!=True:
                    raise LabelError(f"Variable {datadep_var}'s reset is False. But it is a data dependence of {v}")
            self.adj_map_data[v] = data_neighbors

            # For control-only flow
            if v.line not in self.adj_map_control:
                control_neighbors: List[int] = [v.line for v in v.control_dep]
                self.adj_map_control[v.line] = control_neighbors

    def set_target_var(self, target_var:str):
        varname, linenum = parse_single_entry(target_var)
        if not self.var_exist(varname, linenum):
            raise LabelError(f"Missing entry: {target_var}.")
        self.target_var = self.vars[varname][linenum]

    def set_other_vars(self, other_vars:List[str]):
        for var in other_vars if other_vars else []:
            varname, linenum = parse_single_entry(var)
            if self.var_exist(varname, linenum):
                raise LabelError(f"Other var {var} exists.")
            self.other_vars.add(Variable(varname, linenum))

    def set_early_return_lines(self, early_returns:List[int]):
        if not early_returns:
            early_returns = []
        self.early_return_lines = set(early_returns)
        for var in self.all_vars:
            if var.line in early_returns and var.reset_value:
                print(f"Warning: {self.label_fpath}: variable {var} at early return line {var.line} has value reset.")

    
    def set_subscript_vars(self, subscript_vars:List[str]):
        for var in subscript_vars if subscript_vars else []:
            varname = var
            if not self.var_exist(varname):
                self.subscript.add(varname)
                # raise LabelError(f"Subscript var {var} does not exist.")
            for l in self.vars[varname]:
                self.vars[varname][l].set_subscript()

    def check_controldep_consistent(self) -> bool:
        # check if variables from the same line have the same control dep
        line_2_var = defaultdict(list)
        inconsistent_vargroups = []
        for var in self.vars:
            for lineno in self.vars[var]:
                line_2_var[lineno].append(self.vars[var][lineno])
        
        for lineno in line_2_var:
            controldep = None
            for var in line_2_var[lineno]:
                if controldep is not None and var.control_dep != controldep:
                    inconsistent_vargroups.append(line_2_var[lineno])
                controldep = var.control_dep
        if inconsistent_vargroups:
            raise LabelError(f"Controldep for variable groups {inconsistent_vargroups} are not consistent." )
        return inconsistent_vargroups == []

    def get_variable(self, varname: str=None, linenum: int=-1) -> Union[Variable, None]:
        """
        Safely get a Variable object from self.vars if it exists,
        otherwise return None.
        """
        # ---------------- named lookup ----------------
        if varname is not None:
            # Known name → delegate to the vars dict
            return self.vars.get(varname, {}).get(linenum, None)

        # ---------------- anonymous lookup ----------------
        if linenum < 0:
            # Not enough info
            return None

        for v in self.all_vars:
            if v.line == linenum:
                return v    # return first match

        return None

    def average_varname_length(self) -> float:
        """
        Calculate average length of variable names in the list using average_length.
        """
        names = [var.var for var in self.all_vars]
        return average_length(names)
    
    def all_data_dep_src_vars(self, dst_var:Variable, include_self:bool=False) -> Set[Variable]:
        # return all variables that have data flow influence of the target var
        seen = set()
        queue = [dst_var]
        results = set()
        self_dep_found = False   # flag for earlier write of same var‑name
        while queue:
            curr = queue.pop(0)
            seen.add(curr)
            # Exclude dst_var itself unless include_self=True
            if curr!=dst_var and curr.reset_value!=False:
                # curr.reset_value==False: variables introduced with control flow
                results.add(curr)
            for curr_datadep in curr.data_dep:
                if curr_datadep not in seen:
                    queue.append(curr_datadep)
                if curr_datadep==dst_var:
                    self_dep_found=True


        if include_self and self_dep_found:
            results.add(dst_var)
        return results

    def sample_datadep_target(self, n: int) -> Set["Variable"]:
        """
        Sample up to `n` data-dependency-valid variables from self.all_vars.

        Constraints:
        - Always include self.target_var.
        - Each added variable must:
            1. Be valid under check_target_valid_datadep()
            2. Have reset_value == True
            3. Not be in the data-dep source set of any selected variable (blocked)
            # 4. Not have any of its own data-dep sources inside selected (upstream conflict)
        """
        if self.target_var is None:
            return set()

        selected: Set[Variable] = {self.target_var}
        blocked: Set[Variable] = self.all_data_dep_src_vars(self.target_var)

        candidates = list(self.all_vars)
        random.shuffle(candidates)

        for var in candidates:
            if len(selected) >= n:
                break
            if (
                var in selected
                or var in blocked
                or not var.reset_value
                or not self.check_target_valid_datadep(var)
            ):
                continue

            upstream = self.all_data_dep_src_vars(var)
            # if selected.intersection(upstream):
            #     continue  # violates reverse direction constraint

            selected.add(var)
            blocked.update(upstream)

        return selected


    def sample_implicit_target(self, n: int, max_depth:int=-1) -> Set["Variable"]:
        """
        Sample up to `n` implicit-dependency-valid variables from self.all_vars.

        Constraints:
        - Always include self.target_var.
        - Each added variable must:
            1. Be valid under check_target_valid_implicitdep()
            2. Have reset_value == True
            3. Not be in the data-dep source set of any selected variable (blocked)
            # 4. Not have any of its own data-dep sources inside selected (upstream conflict)
        """
        if self.target_var is None:
            return set()

        selected: Set[Variable] = set() # {self.target_var}
        blocked: Set[Variable] = set() #self.all_implicit_src_vars(self.target_var, return_one_set=True)

        candidates = list(self.all_vars)
        random.shuffle(candidates)

        for var in candidates:
            if len(selected) >= n-1:
                break
            if (
                var in selected
                or var in blocked
                or not var.reset_value
                or not self.check_target_valid_implicitdep(var)
            ):
                continue

            upstream = self.all_implicit_src_vars(var, return_one_set=True, max_depth=max_depth)
            # if selected.intersection(upstream):
            #     continue  # violates reverse direction constraint

            selected.add(var)
            blocked.update(upstream)
        
        selected.add(self.target_var)

        return selected
    

    def sample_controldep_target(self, n: int, depth: int = 2) -> Set["Variable"]:
        """
        Sample up to `n` valid control-dependency-based variables from self.all_vars.

        Constraints:
        - Must pass check_target_valid_controldep(var)
        - Must have reset_value == True
        - The first `depth` layers of control-dependency lines must not be in blocked_lines
        """
        

        def get_control_dep_lines(var: Variable, max_depth: int) -> Set[int]:
            """Collect control-dependency lines up to `max_depth` from var."""
            seen = set()
            queue = [(var, 0)]
            lines = set()
            while queue:
                curr, dist = queue.pop(0)
                if dist >= max_depth:
                    continue
                for pred in curr.control_dep:
                    if pred.line not in seen:
                        seen.add(pred.line)
                        lines.add(pred.line)
                        queue.append((pred, dist + 1))
            return lines

        if self.target_var is None:
            return set()

        selected: Set[Variable] = {self.target_var}
        blocked_lines: Set[int] = get_control_dep_lines(self.target_var, max_depth=depth)
        candidates = list(self.all_vars)
        random.shuffle(candidates)

        for var in candidates:
            
            if len(selected) >= n:
                break
            if (
                var in selected
                or not var.reset_value
                or not self.check_target_valid_controldep(var)
            ):
                continue

            control_lines = get_control_dep_lines(var, max_depth=depth)
            if blocked_lines.intersection(control_lines):
                continue  # this variable's control-dep lines overlap with blocked ones

            selected.add(var)
            blocked_lines.update(control_lines)

        return selected
    

    def check_target_valid_datadep(self, var: "Variable") -> bool:
        """
        Return True iff:
        - there exists a data-dependency chain that satisfies EITHER:
            a) has ≥ 2 edges
            b) has ≥ 1 unique upstream variables (excluding var itself)
        """
        if var is None:
            # or not var.control_dep:
            return False

        # Stack holds: (current_node, distance_from_var, set_of_upstream_vars)
        stack = [(var, 0, set())]

        while stack:
            curr, dist, upstream_vars = stack.pop()

            for pred in curr.data_dep:
                if pred in upstream_vars:
                    continue

                new_dist = dist + 1
                new_upstream_vars = upstream_vars | {pred}

                # ----- relaxed success condition -----
                if new_dist >= 2 or len(new_upstream_vars) >= 1:
                    return True

                stack.append((pred, new_dist, new_upstream_vars))

        return False
    
    def check_target_valid_implicitdep(self, var: "Variable") -> bool:
        def _control_in_datadep(dst: "Variable") -> bool:
            """
            Check if any variable in dst's data-dependency source set has a control dependency.
            Returns True if at least one such variable has non-empty control_dep, otherwise False.
            """
            # Collect all variables that feed into dst via data dependencies
            data_src_vars: Set[Variable] = self.all_data_dep_src_vars(dst)
            data_src_vars.add(dst)
            # Check each for a control dependency
            for var in data_src_vars:
                if var.control_dep:
                    if len(var.control_dep)==1 and  next(iter(var.control_dep)).var=='Null':
                        continue
                    else:
                        return True
            return False
        
        return self.check_target_valid_datadep(var) and _control_in_datadep(var)
    
    def check_target_valid_controldep(self, var: "Variable") -> bool:
        """
        Return True iff there exists a control-dependency chain into `var`
        with at least 2 lines (i.e. 3 nodes including var).
        """
        if var is None:
            return False

        stack = [(var, 0)]
        visited = {var.line}

        while stack:
            curr, dist = stack.pop()

            for pred in curr.control_dep:
                if pred in visited:
                    continue
                if pred.line == curr.line:
                    continue

                new_dist = dist + 1
                if new_dist >= 2:
                    return True

                visited.add(pred.line)
                stack.append((pred, new_dist))

        return False




    def data_dep_trace(self, src_var: Variable, dst_var: Variable) -> List[List[Variable]]:
        """
        Return all acyclic paths (no repeated nodes) from `dst_var` back to `src_var`,
        exploring only data_dep edges.  Uses (node, visited)-based memoization
        to reduce redundant sub-DFS calls.

        Each returned path is in the order [src_var, ..., dst_var].
        """

        memo = {}  # key: (Variable, frozenset_of_visited) -> List of paths [dst->...->src]
                # Each path is stored as a list of Variables in *reverse* order.

        def dfs(current: Variable, visited: Set[Variable]) -> List[List[Variable]]:
            # If we reached the source, there's exactly one path: [src_var]
            if current == src_var:
                return [[src_var]]

            # Check if we've already computed all paths from (current, visited)
            key = (current, frozenset(visited))
            if key in memo:
                return memo[key]

            paths = []
            # Gather parents from data_dep
            for dep in current.data_dep:
                # If we haven't visited 'dep' yet in this path, explore
                if dep not in visited:
                    subpaths = dfs(dep, visited | {dep})
                    # Prepend 'current' to each subpath
                    for sp in subpaths:
                        # sp is [dep->...->src], so new path is [current->dep->...->src]
                        paths.append([current] + sp)

            # Deduplicate paths (in case of overlap) by storing them as tuples in a set
            unique_path_tuples = set(tuple(p) for p in paths)
            # Convert back to lists
            unique_paths = [list(t) for t in unique_path_tuples]

            memo[key] = unique_paths
            return unique_paths

        # Start DFS from dst_var, marking it visited
        all_reversed_paths = dfs(dst_var, visited={dst_var})

        # Currently, each path is from [dst_var -> ... -> src_var].
        # Reverse to get [src_var, ..., dst_var].
        final_paths = [p[::-1] for p in all_reversed_paths]
        return final_paths

    def data_dep_neg(self, dst_var:Variable, scan_results: Dict) -> Set[Variable]:
        # list all negative samples that don't have data flow influence on dst_var
        neg_vars = set()
        neg_vars_after_target = set()
        all_data_dep_vars = self.all_data_dep_src_vars(dst_var)
        condition_blocks = self.get_condition_blocks(scan_results)
        for var in set(self.all_vars).union(self.other_vars):
            if var==dst_var or var in all_data_dep_vars or var.reset_value!=True:
                continue
            if  var.line < dst_var.line:
                neg_vars.add(var)
            elif self._in_same_loop_block(dst_var.line, var.line, condition_blocks):
                neg_vars_after_target.add(var)

        return neg_vars, neg_vars_after_target

    def all_control_dep_lines(self,
                          dst_var: "Variable",
                          include_self: bool = True) -> List[int]:
        """
        Collect every source line that controls `dst_var`.

        • Always returns lines of *other* variables that (transitively) control
        `dst_var`.
        • Adds `dst_var.line` itself **only if**
            – `include_self` is True, **and**
            – some control‑dependency path reaches a variable whose line number
            equals `dst_var.line` but is *not* the same variable instance
            (i.e. the value truly depends on a prior evaluation on that line,
            not merely because we started the search there).
        """
        seen_vars:   set  = set()
        queue:       list = [dst_var]
        result_lines: set = set()
        self_dep_found = False     # flag for genuine self‑control‑dependence

        while queue:
            curr = queue.pop(0)
            seen_vars.add(curr)

            # For lines other than the destination's own, always include
            if curr != dst_var:
                result_lines.add(curr.line)

            for pred in curr.control_dep:
                if pred not in seen_vars:
                    queue.append(pred)

                # Detect an ancestor on the same source line
                if pred.line == dst_var.line and pred != dst_var:
                    self_dep_found = True

        # Add self line only when requested and justified
        if include_self and self_dep_found:
            result_lines.add(dst_var.line)

        return sorted(result_lines)
    

    def control_dep_trace(self, src_line:int, dst_var:Variable) -> List[List[int]]:
        all_paths = []
        def _dfs(var, path):
            # print(path)
            if var.line in path:
                return
            if var.line == src_line:
                if path+[var.line] not in all_paths:
                    all_paths.append(path+[var.line])
                return
            if not var.control_dep:
                return
            else:
                for depvar in var.control_dep:
                    if depvar.line not in path and depvar!=var:
                        _dfs(depvar, path+[var.line])
        _dfs(dst_var, [])
        # print(all_paths)
        if len(all_paths)!=1:
            print(f"len(all_paths)!=1, label file: {self.label_fpath}, src: {src_line}, dst: {dst_var.line}. all paths = {all_paths}")
        # assert len(all_paths) == 1
        all_paths = [p[::-1] for p in all_paths]
        for path in all_paths:
            assert path[0] == src_line and path[-1] == dst_var.line, f"Trace line doesn't match {src_line} -> {dst_var.line}: {path}"
        return all_paths

    # DEPRECATED
    def evaluate_control_dep_trace(
        self,
        ground_truth: List[int],
        candidate: List[int],
        verbose: bool = False
    ) -> Dict[str, float]:
        """
        Evaluate a candidate control-dependency trace against a ground-truth set of lines.
        The traces are simply lists of line numbers, and we ignore any ordering:
        
        - Precision = (# lines both in candidate + ground_truth) / (# lines in candidate)
        - Recall = (# lines both in candidate + ground_truth) / (# lines in ground_truth)

        Return a dictionary with 'precision' and 'recall'. 
        """
        # Convert both lists to sets for easier set-based operations
        gt_set = set(ground_truth)
        cand_set = set(candidate)

        # If both are empty, define precision and recall = 1.0, or handle as special case
        if not gt_set and not cand_set:
            return {"num_correct": 0, "precision": 1.0, "recall": 1.0}

        # Intersection: lines that appear in both
        intersection = gt_set.intersection(cand_set)
        true_positives = len(intersection)

        # Compute precision
        if len(cand_set) == 0:
            precision = 1.0 if len(gt_set) == 0 else 0.0
        else:
            precision = true_positives / len(cand_set)

        # Compute recall
        if len(gt_set) == 0:
            recall = 1.0 if len(cand_set) == 0 else 0.0
        else:
            recall = true_positives / len(gt_set)

        results = {
            "num_correct": true_positives,
            "total_gt": len(gt_set),
            "total_pred": len(cand_set),
            "precision": precision,
            "recall": recall
        }

        if verbose:
            print("---- CONTROL DEP TRACE EVALUATION ----")
            print(f"Ground Truth lines: {gt_set}")
            print(f"Candidate lines: {cand_set}")
            print(f"Intersection (correct lines): {intersection}")
            print(f"Precision: {precision:.3f}  (TP={true_positives}, Candidate size={len(cand_set)})")
            print(f"Recall: {recall:.3f}  (TP={true_positives}, Ground Truth size={len(gt_set)})")

        return results

    def get_condition_blocks(self, scan_results):
        # --------------------------------------------------------------------
        # 1) Collect all condition blocks
        # We'll define a small helper to gather them from the if_statements and loop_statements
        # inside the given 'scan_results'. This might depend on how your data is organized.
        # Suppose scan_results is a single function's scan info with "if_statements" & "loop_statements".
        # Or it might be the entire JSON, in which case you pick the correct entry. 
        # Adjust as needed.
        # --------------------------------------------------------------------

        condition_blocks = []
        # if_statements
        if_list = scan_results.get("if_statements", [])
        for ifinfo in if_list:
            # condition_range might be something like (cond_line, start_line, end_line)
            c_line, s_line, e_line = condition_range(ifinfo)  
            condition_blocks.append(('if', c_line, s_line, e_line))

        # loop_statements
        loop_list = scan_results.get("loop_statements", [])
        for loopinfo in loop_list:
            c_line, s_line, e_line = condition_range(loopinfo)
            condition_blocks.append(('loop', c_line, s_line, e_line))
        
        return condition_blocks
    
    def _in_same_loop_block(self, line1: int, line2: int, condition_blocks: List[Tuple[str, int, int, int]]) -> bool:
        """
        Check whether both line1 and line2 are inside the same loop block.

        Returns True if there exists a loop block such that:
        start_line <= line1 <= end_line AND start_line <= line2 <= end_line
        """
        for (block_type, _, start_line, end_line) in condition_blocks:
            if block_type != "loop":
                continue
            if start_line <= line1 <= end_line and start_line <= line2 <= end_line:
                return True
        return False
    

    def control_dep_neg(self, dst_var: "Variable", scan_results: Dict) -> List[int]:
        """
        Return all condition lines (from if/loop statements) that do NOT control dst_var.
        
        Steps:
        1) Collect all condition blocks from scan_results, each has (cond_line, start_line, end_line).
        2) controlling_lines = self.all_control_dep_lines(dst_var, include_self=True)
        3) For each block:
            - if cond_line < dst_line:
                -> include cond_line if it's not in controlling_lines
            - else if cond_line > dst_line:
                -> include cond_line if it's in the "same block" as dst_line
                    and cond_line not in controlling_lines
        """
        target_line = dst_var.line
        
        condition_blocks = self.get_condition_blocks(scan_results)

        # --------------------------------------------------------------------
        # 2) controlling_lines => set of lines that DO control dst_var
        #    (We skip them in final results.)
        # --------------------------------------------------------------------
        controlling_lines = set(self.all_control_dep_lines(dst_var, include_self=True))

        # --------------------------------------------------------------------
        # 3) Build final results
        # --------------------------------------------------------------------
        candidate = []
        candidates_after_target = []
        for (_, cond_line, start_line, end_line) in condition_blocks:
            # If this condition line is controlling dst_var, skip
            if cond_line in controlling_lines:
                continue

            if cond_line < target_line:
                # If cond_line is before target, we want it only if it's not in controlling set
                # We already checked cond_line not in controlling_lines, so we can add it
                candidate.append(cond_line)

            elif cond_line > target_line:
                # If cond_line is after target, we only consider it if they are in the "same LOOP block."
                # For example, "same block" means target_line >= start_line && target_line <= end_line
                # so the target is inside that block's range.
                # Then also cond_line not in controlling_lines, which we've checked.
                if self._in_same_loop_block(target_line, cond_line, condition_blocks):
                    candidates_after_target.append(cond_line)
                else:
                    # not same block => skip
                    pass

            else:
                # cond_line == target_line? Probably doesn't happen for condition lines, but if so, skip or handle
                pass

        return sorted(candidate), sorted(candidates_after_target) 
    


    def process_candidate_trace(self, candidate_trace: List[Tuple[str,int]]) -> List["Variable"]:
        """
        Convert (varname, linenum) list into a list of Variable objects.
        If not found in self.vars, create a new one and store it in both 
        self.vars[varname][linenum] and self.all_vars.

        e.g. candidate_trace = [('sk', 28), ('sk', 39), ('sk', 70), ('d', 71)]
         -> [Variable('sk', 28), Variable('sk', 39), Variable('sk', 70), Variable('d', 71)]
        """
        result = []
        for (varname, linenum) in candidate_trace:
            var_obj = self.get_variable(varname, linenum)
            if var_obj is None:
                # Create a new Variable
                var_obj = Variable(varname, linenum)
                # Store in self.vars
                if varname not in self.vars:
                    self.vars[varname] = {}
                self.vars[varname][linenum] = var_obj
                # Also store in self.all_vars
                self.all_vars.append(var_obj)

            result.append(var_obj)

        return result
        
    def all_implicit_src_vars(self, dst_var: Variable, max_depth: int = -1, return_one_set: bool = False, include_self:bool=False) -> Tuple[Set[Variable], Set[Variable]]:
        """
        Return implicit-source variables feeding into dst_var via data or control deps.
        Splits into primary (no data-dep) and secondary (has data-dep) sets.
        If max_depth >= 0, only traverse up to that depth. If max_depth < 0, traverse fully.
        If return_one_set=True, merges and returns a single set.
        """
        seen: Set[Variable] = set()
        queue: deque = deque([(dst_var, 0)])
        primary_candidate: Set[Variable] = set()
        secondary_candidate: Set[Variable] = set()
        vars_has_datadep = self.all_data_dep_src_vars(dst_var)
        self_dep_found = False
        while queue:
            curr, depth = queue.popleft()
            if curr in seen:
                continue
            seen.add(curr)
            if curr != dst_var and curr.reset_value:
                if curr in vars_has_datadep:
                    secondary_candidate.add(curr)
                else:
                    primary_candidate.add(curr)
            # Enforce depth if specified
            if max_depth >= 0 and depth >= max_depth:
                continue
            # Enqueue both data and control predecessors
            for pred in curr.data_dep.union(curr.control_dep):
                if pred not in seen:
                    queue.append((pred, depth + 1))

                # Detect a cycle that revisits dst_var
                if pred == dst_var:
                    self_dep_found = True

        # Add dst_var itself only if requested *and* a real self‑dependency exists
        if include_self and self_dep_found and dst_var.reset_value:
            if dst_var in vars_has_datadep:
                secondary_candidate.add(dst_var)
            else:
                primary_candidate.add(dst_var)
                
        if return_one_set:
            return primary_candidate.union(secondary_candidate)
        return primary_candidate, secondary_candidate



    def implicit_neg_vars(self, dst_var:Variable, scan_results: Dict) -> Tuple[Set[Variable],Set[Variable]]:
        primary, secondary = self.all_implicit_src_vars(dst_var)
        all_implicit_src_vars = primary.union(secondary)

        vars_has_datadep = self.all_data_dep_src_vars(dst_var)
        assert vars_has_datadep.issubset(all_implicit_src_vars)
        
        primary_candidate = set()     # appear before target
        secondary_candidate = set()   # appear after target
        condition_blocks = self.get_condition_blocks(scan_results)
        for var in self.all_vars + list(self.other_vars):
            if var in all_implicit_src_vars or var.reset_value!=True or var==dst_var:
                continue
            if var.line<dst_var.line:
                primary_candidate.add(var)
            elif self._in_same_loop_block(dst_var.line, var.line, condition_blocks):
                secondary_candidate.add(var)
            
            
        return primary_candidate, secondary_candidate
    
    # TODO: if variable reset=False, only print line number
    def shortest_path_bfs(
        self,
        adjacency: Dict[Union[int,"Variable"], List[Union[int,"Variable"]]],
        src: Union[int,"Variable"],
        dst: Union[int,"Variable"]
    ) -> Optional[List[Union[int,"Variable"]]]:
        """
        Given a reversed adjacency 'adjacency', do a BFS starting at `dst`
        to find `src`.  If found, reconstruct the path [src, ..., dst].

        Return None if no path exists.
        """
    
        if dst not in adjacency:
            return None

        queue = deque([dst])
        visited = {dst}
        parent = {dst: None}

        found_src = False
        while queue:
            current = queue.popleft()
            if current == src:
                found_src = True
                break

            # adjacency[current] should be the list of predecessors of `current`
            for pred in adjacency.get(current, []):
                if pred not in visited:
                    visited.add(pred)
                    parent[pred] = current
                    queue.append(pred)

        if not found_src:
            return None

        # Reconstruct path forward: [src, ..., dst]
        path = []
        node = src
        while node is not None:
            path.append(node)
            node = parent[node]
        return path

    # TODO: update when variable reset=False
    def evaluate_trace(
        self,
        adjacency: Dict[Union[int,"Variable"], List[Union[int,"Variable"]]],
        candidate_trace: List[Union[int,"Variable"]],
        verbose: bool = False
    ) -> Dict[str, float]:
        """
        Evaluate a candidate trace using the given reversed adjacency.

        1) Precision = (# correct edges) / (# total edges).
        2) WRONG edges = edges not in adjacency:
        - If no path from b to a => false edge
        - else => inaccurate edge, missing_nodes=(shortest_path_length-2)
        Returns a dict with:
        {
            "correct_edges": ...,
            "total_edges": ...,
            "precision": ...,
            "num_false_edges": ...,
            "num_inaccurate_edges": ...,
            "missing_nodes": ...
        }
        """
        results = {
            "correct_edges": 0,
            "total_edges": 0,
            "precision": 0.0,
            "num_false_edges": 0,
            "num_inaccurate_edges": 0,
            "missing_nodes": 0.0
        }

        # If there are fewer than 2 variables, no edges
        if not candidate_trace or len(candidate_trace) < 2:
            return results

        trace_forward = candidate_trace[::-1]
        total_edges = len(trace_forward) - 1
        correct_edges = 0

        sum_missing_nodes = 0

        for i in range(total_edges):
            a = trace_forward[i]
            b = trace_forward[i + 1]

            # Check immediate adjacency in reversed sense:
            # if b is in adjacency[a], that means (b->a) is correct in forward logic.
            preds_of_a = adjacency.get(a, [])
            # print(b, preds_of_b)
            if b in preds_of_a:
                correct_edges += 1
            else:
                # wrong edge -> BFS from b to a
                path = self.shortest_path_bfs(adjacency, b, a)
                if path is None:
                    results["num_false_edges"] += 1
                    if verbose:
                        print(f"False edge: {b}->{a} (no path in graph).")
                else:
                    results["num_inaccurate_edges"] += 1
                    missing = len(path) - 2
                    sum_missing_nodes += missing
                    if verbose:
                        print(f"Inaccurate edge: {b} -> {a}")
                        print(f"  Shortest path: {path}")
                        print(f"  Missing nodes: {missing}")

        results["total_edges"] = total_edges
        results["correct_edges"] = correct_edges
        if total_edges > 0:
            results["precision"] = correct_edges / total_edges

        num_inacc = results["num_inaccurate_edges"]
        # if num_inacc > 0:
        #     results["avg_missing_nodes"] = sum_missing_nodes / num_inacc
        results["missing_nodes"] = sum_missing_nodes

        if verbose:
            print("---- SUMMARY ----")
            print(f"Precision: {results['precision']:.3f}  "
                f"({correct_edges}/{total_edges} correct edges)")
            print(f"False edges: {results['num_false_edges']}")
            print(f"Inaccurate edges: {results['num_inaccurate_edges']}")
            print(f"Missing nodes: {results['missing_nodes']:.3f}")

        return results

    def evaluate_control_trace(self, candidate_trace: List["int"], verbose=False) -> Dict[str, float]:
        """
        Evaluate the candidate_trace using control-dep adjacency only.
        """
        return self.evaluate_trace(self.adj_map_control, candidate_trace, verbose=verbose)
    

    def evaluate_data_trace(self, candidate_trace: List["Variable"], verbose=False) -> Dict[str, float]:
        """
        Evaluate the candidate_trace using data-dep adjacency only.
        """
        return self.evaluate_trace(self.adj_map_data, candidate_trace, verbose=verbose)

    def evaluate_implicit_trace(self, candidate_trace: List["Variable"], verbose=False) -> Dict[str, float]:
        """
        Evaluate the candidate_trace using implicit adjacency (data+control).
        """
        return self.evaluate_trace(self.adj_map_implicit, candidate_trace, verbose=verbose)

    def datadep_complexity(self, src: "Variable", dst: "Variable", include_path:bool=True) -> Optional[Dict[str, int]]:
        """
        Estimate the complexity of data-dependency path from src to dst using shortest_path_bfs.
        Returns dict with 'steps' (edges count) and 'nodes' (variables count), or None if no path.
        """
        path = self.shortest_path_bfs(self.adj_map_data, src, dst)
        if path is None:
            return None
        results = {'steps': len(path) - 1, 'nodes': len(set(path))}
        if include_path:
            results['shortest_path'] =  path
        return results

    def implicit_complexity(self, src: "Variable", dst: "Variable", include_path:bool=True) -> Optional[Dict[str, int]]:
        """
        Estimate the complexity of implicit (data+control) dependency path from src to dst.
        """
        path = self.shortest_path_bfs(self.adj_map_implicit, src, dst)
        if path is None:
            return None
        results = {'steps': len(path) - 1, 'nodes': len(set(path))}
        if include_path:
            results['shortest_path'] =  path
        return results

    def involves_early_return(self, dst: "Variable", max_depth: int) -> int:
        """
        USED for datadep and implicitdep
        Determine if any early-return line influences the path from src to dst.
        Performs a BFS over implicit adjacency (data+control) up to `max_depth` levels.
        Returns the first early-return line number encountered, or -1 if none.
        """
        visited: Set[Variable] = set([dst])
        queue = deque([(dst, 0)])  # (current var, depth)

        while queue:
            curr, depth = queue.popleft()
            if depth > max_depth:
                continue

            # Check if any of curr's control-dependencies are early returns
            ctrl_lines = {v.line for v in curr.control_dep}
            overlap = ctrl_lines.intersection(self.early_return_lines)
            if overlap:
                # return any one matching line
                return next(iter(overlap))

            # Enqueue implicit predecessors using adj_map_implicit
            for pred in self.adj_map_implicit.get(curr, []):
                if pred not in visited:
                    visited.add(pred)
                    queue.append((pred, depth + 1))

        return -1
    
    def controldep_involves_early_return(self, ground_truth:List[List[int]]) -> int:
        for gt in ground_truth:
            overlap = set(gt).intersection(self.early_return_lines)
            if overlap:
                # return any one matching line
                return next(iter(overlap))
        return -1   
    
    def evaluate_control_sources(self,
                             dst_var: "Variable",
                             pred_lines: List[int],
                             include_self: bool = True) -> Dict[str, Any]:
        """Evaluate control‑dependency *source lines* prediction."""
        gt = set(self.all_control_dep_lines(dst_var, include_self=include_self))
        pred = set(pred_lines)
        metrics = _precision_recall_f1(pred, gt)
        metrics["ground_truth"] = list(sorted(gt))
        return metrics



    def evaluate_data_sources(self,
                          dst_var: "Variable",
                          pred_pairs: List[Tuple[str, int]],
                          include_self: bool = True) -> Dict[str, Any]:
        """Evaluate data‑dependency *source variables* prediction."""
        pred_vars = set(self.process_candidate_trace(pred_pairs))
        gt_vars = self.all_data_dep_src_vars(dst_var, include_self=include_self)
        metrics = _precision_recall_f1(pred_vars, gt_vars)
        metrics["ground_truth"] = [v.to_list() for v in sorted(gt_vars, key=lambda x: (x.var, x.line))]
        return metrics

    def evaluate_implicit_sources(self,
                              dst_var: "Variable",
                              pred_pairs: List[Tuple[str, int]],
                              max_depth: int = -1,
                              include_self: bool = True) -> Dict[str, Any]:
        """Evaluate *implicit* source prediction."""
        pred_vars = set(self.process_candidate_trace(pred_pairs))
        gt_set = self.all_implicit_src_vars(dst_var,
                                            max_depth=max_depth,
                                            return_one_set=True,
                                            include_self=include_self)
        metrics = _precision_recall_f1(pred_vars, gt_set)
        metrics["ground_truth"] = [v.to_list() for v in sorted(gt_set, key=lambda x: (x.var, x.line))]
        return metrics
