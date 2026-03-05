from collections import defaultdict, deque

class GraphValidator:

    def __init__(self, components, connections):
        # We use the component instance itself as the node identifier
        self.components = components
        self.connections = connections
        
        self.adj_list = defaultdict(list)
        self.in_degree = defaultdict(int)
        self.out_degree = defaultdict(int)
        
        self._build_graph()

    def _build_graph(self):
        # Initialize counts for all components
        for comp in self.components:
            self.in_degree[comp] = 0
            self.out_degree[comp] = 0
            # Ensure the component exists in the adjacency list even if disconnected
            _ = self.adj_list[comp]

        for conn in self.connections:
            # ONLY process connection if both ends are currently ON the canvas
            if conn.start_component in self.components and conn.end_component in self.components:
                u = conn.start_component
                v = conn.end_component
                self.adj_list[u].append(v)
                self.out_degree[u] += 1
                self.in_degree[v] += 1

    def validate(self):
        isolated = self._find_isolated()
        loops = self._find_loops_dfs()
        
        flow_errors, unreachable_from_inlet, cant_reach_outlet, missing_inlet, missing_outlet = self._validate_flow_bfs()

        return {
            "isolated": isolated,
            "loops": loops,
            "flow_errors": flow_errors,
            "unreachable_from_inlet": unreachable_from_inlet,
            "cant_reach_outlet": cant_reach_outlet,
            "missing_inlet": missing_inlet,
            "missing_outlet": missing_outlet
        }


    def _find_isolated(self):
        """Identify components with 0 connections."""
        isolated = []
        for comp in self.components:
            if self.in_degree[comp] == 0 and self.out_degree[comp] == 0:
                isolated.append(comp)
        return isolated

    def _find_loops_dfs(self):
        """Identify components involved in circular loops using DFS."""
        visited = set()
        rec_stack = set()
        loop_components = set()

        def dfs(node, path):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self.adj_list[node]:
                if neighbor not in visited:
                    dfs(neighbor, path)
                elif neighbor in rec_stack:
                    # Cycle detected, mark all nodes in the cycle
                    cycle_start_index = path.index(neighbor)
                    for n in path[cycle_start_index:]:
                        loop_components.add(n)

            rec_stack.remove(node)
            path.pop()

        for comp in self.components:
            if comp not in visited:
                dfs(comp, [])

        return list(loop_components)

    def _validate_flow_bfs(self):
        inlets = []
        outlets = []
        
        for comp in self.components:
            name = comp.config.get("object", "").lower()
            # Strongly identify process bounds by name
            if "inflow" in name or "inlet" in name:
                inlets.append(comp)
            elif "outflow" in name or "outlet" in name:
                outlets.append(comp)
        
        missing_inlet = len(inlets) == 0 and len(self.components) > 0
        missing_outlet = len(outlets) == 0 and len(self.components) > 0

        # Run BFS from all inlets to find all reachable nodes
        reachable_from_inlets = set()
        queue = deque(inlets)
        
        while queue:
            curr = queue.popleft()
            if curr not in reachable_from_inlets:
                reachable_from_inlets.add(curr)
                for neighbor in self.adj_list[curr]:
                    queue.append(neighbor)

        flow_errors = set()
        unreachable_from_inlet = set()
        cant_reach_outlet = set()

        # 1. Any non-isolated node unreachable from an inlet is a flow error.
        for comp in self.components:
            if self.in_degree[comp] == 0 and self.out_degree[comp] == 0:
                continue
            if comp not in reachable_from_inlets:
                flow_errors.add(comp)
                unreachable_from_inlet.add(comp)

        # 2. Trace backwards from outlets: nodes that never reach an outlet are dead-ends
        reachable_to_outlets = set()
        reverse_adj_list = defaultdict(list)
        for u in self.adj_list:
            for v in self.adj_list[u]:
                reverse_adj_list[v].append(u)

        rev_queue = deque(outlets)
        while rev_queue:
            curr = rev_queue.popleft()
            if curr not in reachable_to_outlets:
                reachable_to_outlets.add(curr)
                for neighbor in reverse_adj_list[curr]:
                    rev_queue.append(neighbor)

        for comp in self.components:
            if self.in_degree[comp] == 0 and self.out_degree[comp] == 0:
                continue
            if comp not in reachable_to_outlets:
                flow_errors.add(comp)
                cant_reach_outlet.add(comp)

        return list(flow_errors), list(unreachable_from_inlet), list(cant_reach_outlet), missing_inlet, missing_outlet

