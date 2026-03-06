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
        
        flow_errors, missing_inlet, missing_outlet = self._validate_flow_bfs()

        return {
            "isolated": isolated,
            "loops": loops,
            "flow_errors": flow_errors,
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

        flow_errors = set()
        
        # A component MUST have either an inlet or an outlet.
        # If it has 0 incoming AND 0 outgoing connections, it's an error.
        # This replaces the strict path-to-Inlet/Outlet BFS logic.
        for comp in self.components:
            name = comp.config.get("object", "").lower()
            
            # If a standard component has absolutely no connections, it violates the flow rule.
            if self.in_degree[comp] == 0 and self.out_degree[comp] == 0:
                flow_errors.add(comp)

        return list(flow_errors), missing_inlet, missing_outlet
