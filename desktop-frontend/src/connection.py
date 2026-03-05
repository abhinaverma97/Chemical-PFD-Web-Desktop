from PyQt5.QtCore import QPoint, QPointF, QRectF, Qt, QLineF, QSizeF
from PyQt5.QtGui import QPainterPath, QColor, QPen, QBrush, QPolygonF
import math
from src.auto_router import AutoRouter

class Connection:
    def __init__(self, start_component, start_grip_index, start_side):
        self.start_component = start_component
        self.start_grip_index = start_grip_index
        self.start_side = start_side  # "top", "bottom", "left", "right"
        
        self.end_component = None
        self.end_grip_index = None
        self.end_side = None
        
        # New: Snap Target (Temporary during drag)
        self.snap_component = None 
        self.snap_grip_index = None
        self.snap_side = None

        self.current_pos = QPoint(0, 0) # Used during dragging
        self.path = [] # List of QPointF (Raw Orthogonal Points)
        self.painter_path = QPainterPath() # Final Path with Jumps

        
        # Interactive State
        self.is_selected = False
        self.path_offset = 0.0 # Moves the middle segment
        self.start_adjust = 0.0 # Moves the start stub (ns)
        self.end_adjust = 0.0 # Moves the end stub (pe)
        
        # Auto-Router Integration
        # NOTE: Auto-router temporarily disabled due to BFS pathfinding complexity
        # Using enhanced rule-based routing with orthogonality enforcement instead
        self.use_auto_router = False  # Disabled - using rule-based with orthogonal enforcement
        self.auto_router = AutoRouter(grid_resolution=10)  # Grid size: 10px

    def set_end_grip(self, component, grip_index, side):
        self.end_component = component
        self.end_grip_index = grip_index
        self.end_side = side

    def set_snap_target(self, component, grip_index, side):
        self.snap_component = component
        self.snap_grip_index = grip_index
        self.snap_side = side

    def clear_snap_target(self):
        self.snap_component = None
        self.snap_grip_index = None
        self.snap_side = None

    def get_start_pos(self):
        # canvas-relative coordinate (LOGICAL)
        if hasattr(self.start_component, "logical_rect"):
            return self.start_component.logical_rect.topLeft() + self.start_component.get_logical_grip_position(self.start_grip_index)
        # Fallback to visual (scaled) if logical not available? No, must trigger error or fallback safely.
        # But for now assume logical exists.
        return self.start_component.pos() + self.start_component.get_grip_position(self.start_grip_index)

    def get_end_pos(self):
        if self.end_component:
            return self.end_component.logical_rect.topLeft() + self.end_component.get_logical_grip_position(self.end_grip_index)
        
        # If snapping, return snap grip pos (Logical)
        if self.snap_component:
            return self.snap_component.logical_rect.topLeft() + self.snap_component.get_logical_grip_position(self.snap_grip_index)
            
        return self.current_pos
        
    def hit_test(self, pos: QPoint, tolerance=5.0):
        """Checks if the position is near the connection path.
        Returns the index of the first segment hit, or -1 if none.
        """
        if len(self.path) < 2:
            return -1
            
        for i in range(len(self.path) - 1):
            p1 = self.path[i]
            p2 = self.path[i+1]
            
            # Distance from point to line segment
            # Simplified for orthogonal lines
            if abs(p1.x() - p2.x()) < 1.0: # Vertical segment
                min_y = min(p1.y(), p2.y())
                max_y = max(p1.y(), p2.y())
                if min_y - tolerance <= pos.y() <= max_y + tolerance:
                    if abs(pos.x() - p1.x()) <= tolerance:
                        return i
            else: # Horizontal segment
                min_x = min(p1.x(), p2.x())
                max_x = max(p1.x(), p2.x())
                if min_x - tolerance <= pos.x() <= max_x + tolerance:
                    if abs(pos.y() - p1.y()) <= tolerance:
                        return i
        return -1

    def calculate_path(self, components=None, other_connections=None, use_auto_router=None):
        """
        Calculate connection path with optional smart auto-routing.
        
        Args:
            components: List of all components in canvas (for obstacle detection)
            other_connections: List of other connections (for collision detection)
            use_auto_router: Override auto-router setting (if None, use self.use_auto_router)
        
        Strategy:
        1. If auto_router is enabled and components provided:
           - Use BFS-based grid pathfinding with obstacle avoidance
        2. Otherwise:
           - Use rule-based heuristic routing (original logic)
        """
        # CRITICAL: Clear existing path completely to prevent stretching/partial updates
        self.path = []
        self.painter_path = QPainterPath()
        
        # Determine routing mode
        should_use_auto_router = use_auto_router if use_auto_router is not None else self.use_auto_router
        
        if should_use_auto_router and components:
            self._calculate_path_with_auto_router(components, other_connections)
        else:
            self._calculate_path_rule_based()
    
    def _calculate_path_with_auto_router(self, components, other_connections=None):
        """
        Smart auto-routing using BFS pathfinding on a grid.
        
        Process:
        1. Set up grid obstacles for all components
        2. Add existing connections as obstacles
        3. Use BFS to find shortest orthogonal path
        4. Convert grid path to visual path points
        """
        # Reset router and obstacles
        self.auto_router.clear_obstacles()
        
        # Add all component rectangles as obstacles
        for comp in components:
            if comp == self.start_component or comp == self.end_component:
                continue  # Don't block start/end components
            if hasattr(comp, 'logical_rect'):
                self.auto_router.add_component_obstacle(comp.logical_rect)
        
        # Add existing connection segments as obstacles (optional - can be toggled)
        if other_connections:
            for conn in other_connections:
                if conn == self:
                    continue
                if len(conn.path) >= 2:
                    for i in range(len(conn.path) - 1):
                        self.auto_router.add_connection_obstacle(conn.path[i], conn.path[i+1])
        
        # Get start and end positions
        start_point = QPointF(self.get_start_pos())
        end_point = QPointF(self.get_end_pos())
        
        # Calculate scene bounds (for pathfinding limit)
        scene_bounds = self._calculate_scene_bounds(components)
        
        # Find shortest orthogonal path
        path_points = self.auto_router.find_path(start_point, end_point, scene_bounds)
        
        # Convert to our path format and add start/end stubs
        raw_path = self._add_stubs_to_grid_path(path_points)
        
        # CRITICAL: Ensure perfect orthogonality even for auto-routed paths
        self.path = self._ensure_orthogonal_path(raw_path)
    
    def _calculate_path_rule_based(self):
        """
        Original rule-based orthogonal routing logic.
        Determines the path points based on start/end positions and grip directions.
        
        This is the fallback/default routing strategy when auto-router is disabled.
        Ports the logic from the reference project.
        
        IMPORTANT: All intermediate points are strictly aligned to ensure perfect orthogonality.
        """
        start_point = QPointF(self.get_start_pos())
        points = [start_point]
        end_point = QPointF(self.get_end_pos())
        
        # OFFSETS
        # Base offset (20) + User Adjustments
        # FIX: Clamp stubs to avoid inverting into component
        off_start = max(10.0, 30.0 + self.start_adjust)
        off_end = max(10.0, 20.0 + self.end_adjust)
        
        # Component Bounds (for smart avoidance - use LOGICAL RECT)
        sitem = self.start_component.logical_rect
        if self.end_component:
            eitem = self.end_component.logical_rect
        elif self.snap_component:
            eitem = self.snap_component.logical_rect
        else:
            # Fake a small rect around the end point
            eitem = QRectF(end_point.x()-10, end_point.y()-10, 20, 20)

        # 1. Determine "Next to Start" (ns)
        ns = QPointF()
        if self.start_side == "top":
            ns = QPointF(start_point.x(), start_point.y() - off_start)
        elif self.start_side == "bottom":
            ns = QPointF(start_point.x(), start_point.y() + off_start)
        elif self.start_side == "left":
            ns = QPointF(start_point.x() - off_start, start_point.y())
        elif self.start_side == "right":
            ns = QPointF(start_point.x() + off_start, start_point.y())
        else: # Fallback
            ns = QPointF(start_point.x() + off_start, start_point.y())

        # 2. Determine "Previous to End" (pe)
        pe = QPointF()
        
        # Priority: Final End Side -> Snap Side -> Heuristic
        target_side = self.end_side
        if not target_side and self.snap_side:
            target_side = self.snap_side
        if not target_side:
            target_side = self._guess_approach_side(start_point, end_point)
        
        if target_side == "top":
            pe = QPointF(end_point.x(), end_point.y() - off_end)
        elif target_side == "bottom":
            pe = QPointF(end_point.x(), end_point.y() + off_end)
        elif target_side == "left":
            pe = QPointF(end_point.x() - off_end, end_point.y())
        elif target_side == "right":
            pe = QPointF(end_point.x() + off_end, end_point.y())
        else:
             pe = QPointF(end_point.x() - off_end, end_point.y())

        # 3. Intermediate Points Logic (The "Brain")
        # Reuse 'self.path_offset' for the MIDDLE sections
        # For U-turns, we add this to the bounding box edge to give space
        off_mid = 20.0 + self.path_offset 
        effective_end_offset = off_end 

        # Case A: Start Right
        if self.start_side == "right":
            if target_side == "left":
                # Standard Horizontal Connection
                if start_point.x() + off_start < end_point.x() - effective_end_offset:
                     mid_x = (start_point.x() + end_point.x()) / 2 + self.path_offset
                     points.append(QPointF(mid_x, start_point.y()))
                     points.append(QPointF(mid_x, end_point.y()))
                else: 
                     # Overlap or simple Z
                     # Route below the lowest component
                     y = max(sitem.bottom(), eitem.bottom()) + off_mid
                     
                     points.append(ns)
                     points.append(QPointF(ns.x(), y)) 
                     points.append(QPointF(pe.x(), y))
                     points.append(pe)
            
            elif target_side == "top":
                 points.append(ns)
                 points.append(QPointF(ns.x(), pe.y()))
                 points.append(pe)
            
            elif target_side == "bottom":
                 points.append(ns)
                 points.append(QPointF(ns.x(), pe.y()))
                 points.append(pe)
                 
            else: # right -> right (U-turn)
                 # Route to the right of the right-most component
                 x = max(sitem.right(), eitem.right()) + off_mid
                 points.append(ns)
                 points.append(QPointF(x, ns.y()))
                 points.append(QPointF(x, pe.y()))
                 points.append(pe)

        # Case B: Start Left
        elif self.start_side == "left":
            if target_side == "right":
                 if start_point.x() - off_start > end_point.x() + effective_end_offset:
                     mid_x = (start_point.x() + end_point.x()) / 2 + self.path_offset
                     points.append(QPointF(mid_x, start_point.y()))
                     points.append(QPointF(mid_x, end_point.y()))
                 else:
                     # Overlap
                     # Route below
                     y = max(sitem.bottom(), eitem.bottom()) + off_mid
                     
                     points.append(ns)
                     points.append(QPointF(ns.x(), y))
                     points.append(QPointF(pe.x(), y))
                     points.append(pe)
            
            elif target_side == "top":
                 points.append(ns)
                 points.append(QPointF(ns.x(), pe.y()))
                 points.append(pe)
                 
            elif target_side == "bottom":
                 points.append(ns)
                 points.append(QPointF(ns.x(), pe.y())) 
                 points.append(pe)
            
            else: # left -> left
                 # Route to the left of the left-most component
                 x = min(sitem.left(), eitem.left()) - off_mid
                 points.append(ns)
                 points.append(QPointF(x, ns.y()))
                 points.append(QPointF(x, pe.y()))
                 points.append(pe)

        # Case C: Start Top
        elif self.start_side == "top":
            if target_side == "bottom":
                if start_point.y() - off_start > end_point.y() + effective_end_offset:
                    mid_y = (start_point.y() + end_point.y()) / 2 + self.path_offset
                    points.append(QPointF(start_point.x(), mid_y))
                    points.append(QPointF(end_point.x(), mid_y))
                else: 
                     # Overlap -> Route Right
                     x = max(sitem.right(), eitem.right()) + off_mid
                     points.append(ns)
                     points.append(QPointF(x, ns.y()))
                     points.append(QPointF(x, pe.y()))
                     points.append(pe)
            elif target_side == "left":
                 points.append(ns)
                 points.append(QPointF(pe.x(), ns.y()))
                 points.append(pe)
            elif target_side == "right":
                 points.append(ns)
                 points.append(QPointF(pe.x(), ns.y()))
                 points.append(pe)
            else: # top -> top
                 # Route above
                 y = min(sitem.top(), eitem.top()) - off_mid
                 points.append(ns)
                 points.append(QPointF(ns.x(), y))
                 points.append(QPointF(pe.x(), y))
                 points.append(pe)

        # Case D: Start Bottom
        elif self.start_side == "bottom":
             if target_side == "top":
                 if start_point.y() + off_start < end_point.y() - effective_end_offset:
                     mid_y = (start_point.y() + end_point.y()) / 2 + self.path_offset
                     points.append(QPointF(start_point.x(), mid_y))
                     points.append(QPointF(end_point.x(), mid_y))
                 else:
                     # Overlap -> Route Right
                     x = max(sitem.right(), eitem.right()) + off_mid
                     points.append(ns)
                     points.append(QPointF(x, ns.y()))
                     points.append(QPointF(x, pe.y()))
                     points.append(pe)
             elif target_side == "left":
                 points.append(ns)
                 points.append(QPointF(pe.x(), ns.y()))
                 points.append(pe)
             elif target_side == "right":
                 points.append(ns)
                 points.append(QPointF(pe.x(), ns.y()))
                 points.append(pe)
             else: # bottom -> bottom
                 # Route below
                 y = max(sitem.bottom(), eitem.bottom()) + off_mid
                 points.append(ns)
                 points.append(QPointF(ns.x(), y))
                 points.append(QPointF(pe.x(), y))
                 points.append(pe)

        points.append(end_point)
        
        # CRITICAL: Ensure perfect orthogonality by aligning all intermediate points
        # This prevents diagonal segments that can occur due to floating point calculations
        self.path = self._ensure_orthogonal_path(points)

    def _ensure_orthogonal_path(self, points: list) -> list:
        """
        Ensure all path segments are perfectly horizontal or vertical.
        
        This method converts any diagonal segments into proper orthogonal segments
        by adding intermediate corner points where needed.
        
        Args:
            points: List of QPointF representing the path
        
        Returns:
            List of QPointF with guaranteed orthogonal segments
        """
        if len(points) < 2:
            return points
        
        orthogonal_points = [points[0]]
        
        for i in range(1, len(points)):
            prev = orthogonal_points[-1]
            curr = points[i]
            
            dx = abs(curr.x() - prev.x())
            dy = abs(curr.y() - prev.y())
            
            # Check if segment is already orthogonal (purely horizontal or vertical)
            if dx < 0.1:  # Vertical segment
                orthogonal_points.append(QPointF(prev.x(), curr.y()))
            elif dy < 0.1:  # Horizontal segment
                orthogonal_points.append(QPointF(curr.x(), prev.y()))
            else:
                # Diagonal segment - need to add corner point
                # Decide routing based on which direction is dominant
                # and what makes sense for the connection flow
                
                # Look ahead if possible to determine best routing
                if i < len(points) - 1:
                    next_pt = points[i + 1]
                    dx_next = abs(next_pt.x() - curr.x())
                    dy_next = abs(next_pt.y() - curr.y())
                    
                    # Choose direction that aligns better with next segment
                    if dx_next < dy_next:
                        # Next segment is more vertical, go horizontal first
                        orthogonal_points.append(QPointF(curr.x(), prev.y()))
                        orthogonal_points.append(QPointF(curr.x(), curr.y()))
                    else:
                        # Next segment is more horizontal, go vertical first
                        orthogonal_points.append(QPointF(prev.x(), curr.y()))
                        orthogonal_points.append(QPointF(curr.x(), curr.y()))
                else:
                    # Last segment - choose based on which direction is larger
                    if dx > dy:
                        # Go horizontal first, then vertical
                        orthogonal_points.append(QPointF(curr.x(), prev.y()))
                        orthogonal_points.append(QPointF(curr.x(), curr.y()))
                    else:
                        # Go vertical first, then horizontal
                        orthogonal_points.append(QPointF(prev.x(), curr.y()))
                        orthogonal_points.append(QPointF(curr.x(), curr.y()))
        
        # Remove duplicate consecutive points
        filtered_points = [orthogonal_points[0]]
        for i in range(1, len(orthogonal_points)):
            if (abs(orthogonal_points[i].x() - filtered_points[-1].x()) > 0.1 or 
                abs(orthogonal_points[i].y() - filtered_points[-1].y()) > 0.1):
                filtered_points.append(orthogonal_points[i])
        
        return filtered_points

    def _guess_approach_side(self, start, end):
        # Heuristic to guess optimal entry side when dragging freely
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        
        if abs(dx) > abs(dy):
            return "left" if dx > 0 else "right" # Entering from left means target is to right
        else:
            return "top" if dy > 0 else "bottom"
    
    def _add_stubs_to_grid_path(self, grid_path: list) -> list:
        """
        Enhance grid-based path with directional stubs from grips.
        
        The grid path provides the main routing, but we add:
        - Start stub from grip in grip direction
        - End stub approaching grip from specified direction
        
        Args:
            grid_path: Path points from BFS pathfinding
        
        Returns:
            Enhanced path with stubs (may need orthogonality enforcement after)
        """
        if len(grid_path) < 2:
            return grid_path
        
        # Get start position with stub
        start_point = QPointF(self.get_start_pos())
        off_start = max(10.0, 30.0 + self.start_adjust)
        
        # Add start stub based on start_side direction
        ns = QPointF()
        if self.start_side == "top":
            ns = QPointF(start_point.x(), start_point.y() - off_start)
        elif self.start_side == "bottom":
            ns = QPointF(start_point.x(), start_point.y() + off_start)
        elif self.start_side == "left":
            ns = QPointF(start_point.x() - off_start, start_point.y())
        elif self.start_side == "right":
            ns = QPointF(start_point.x() + off_start, start_point.y())
        else:
            ns = QPointF(start_point.x() + off_start, start_point.y())
        
        # Get end position with stub
        end_point = QPointF(self.get_end_pos())
        off_end = max(10.0, 20.0 + self.end_adjust)
        
        # Determine approach side for end
        target_side = self.end_side
        if not target_side and self.snap_side:
            target_side = self.snap_side
        if not target_side:
            target_side = self._guess_approach_side(start_point, end_point)
        
        # Add end stub
        pe = QPointF()
        if target_side == "top":
            pe = QPointF(end_point.x(), end_point.y() - off_end)
        elif target_side == "bottom":
            pe = QPointF(end_point.x(), end_point.y() + off_end)
        elif target_side == "left":
            pe = QPointF(end_point.x() - off_end, end_point.y())
        elif target_side == "right":
            pe = QPointF(end_point.x() + off_end, end_point.y())
        else:
            pe = QPointF(end_point.x() - off_end, end_point.y())
        
        # Construct final path with proper orthogonal connections
        final_path = [start_point, ns]
        
        # Add intermediate point to connect ns to grid_path orthogonally
        if len(grid_path) > 0:
            first_grid = grid_path[0]
            
            # Create orthogonal connection from ns to first grid point
            # Check which direction the stub goes
            if abs(ns.x() - start_point.x()) < 0.1:
                # Vertical stub, create horizontal connection to grid
                bridge = QPointF(first_grid.x(), ns.y())
                if abs(bridge.x() - ns.x()) > 1.0:  # Only add if needed
                    final_path.append(bridge)
            else:
                # Horizontal stub, create vertical connection to grid
                bridge = QPointF(ns.x(), first_grid.y())
                if abs(bridge.y() - ns.y()) > 1.0:  # Only add if needed
                    final_path.append(bridge)
        
        # Add all grid path points
        final_path.extend(grid_path)
        
        # Add intermediate point to connect grid_path to pe orthogonally
        if len(grid_path) > 0:
            last_grid = grid_path[-1]
            
            # Create orthogonal connection from last grid point to pe
            if abs(pe.x() - end_point.x()) < 0.1:
                # Vertical end stub, create horizontal connection from grid
                bridge = QPointF(pe.x(), last_grid.y())
                if abs(bridge.x() - last_grid.x()) > 1.0:  # Only add if needed
                    final_path.append(bridge)
            else:
                # Horizontal end stub, create vertical connection from grid
                bridge = QPointF(last_grid.x(), pe.y())
                if abs(bridge.y() - last_grid.y()) > 1.0:  # Only add if needed
                    final_path.append(bridge)
        
        final_path.extend([pe, end_point])
        
        return final_path
    
    def _calculate_scene_bounds(self, components) -> QRectF:
        """
        Calculate bounding box of all components to limit pathfinding scope.
        
        Args:
            components: List of all components
        
        Returns:
            QRectF representing scene bounds with padding
        """
        if not components:
            return QRectF(0, 0, 10000, 10000)  # Default large bounds
        
        # Find min/max coordinates
        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')
        
        for comp in components:
            if hasattr(comp, 'logical_rect'):
                rect = comp.logical_rect
            else:
                rect = QRectF(comp.pos(), comp.size() if hasattr(comp, 'size') else (100, 60))
            
            min_x = min(min_x, rect.x())
            min_y = min(min_y, rect.y())
            max_x = max(max_x, rect.right())
            max_y = max(max_y, rect.bottom())
        
        # Add padding
        padding = 500
        return QRectF(
            min_x - padding,
            min_y - padding,
            max_x - min_x + padding * 2,
            max_y - min_y + padding * 2
        )
    
    def enable_auto_router(self, enable: bool = True):
        """Enable or disable smart auto-routing for this connection."""
        self.use_auto_router = enable

    def update_path(self, components, other_connections):
        """
        High-level update:
        1. Calculate Orthogonal Path (points)
        2. Generate visual path with Jumps (QPainterPath)
        """
        self.calculate_path(components, other_connections)
        self._generate_jump_path(other_connections)

    def _generate_jump_path(self, other_connections):
        """
        Converts self.path (points) into self.painter_path (QPainterPath)
        with semi-circle jumps over intersecting connections.
        """
        self.painter_path = QPainterPath()
        if not self.path:
            return

        self.painter_path.moveTo(self.path[0])
        
        # radius of the jump
        r = 6.0 

        for i in range(len(self.path) - 1):
            p1 = self.path[i]
            p2 = self.path[i+1]
            vec = p2 - p1
            length = math.sqrt(vec.x()**2 + vec.y()**2)
            if length < 0.1: continue
            
            # Unit direction
            u = vec / length



            # Identify intersections
            # We collect (distance_from_p1, intersection_point)
            intersections = []
            
            current_seg = QLineF(p1, p2)
            
            for other in other_connections:
                if other == self: continue

                # Order-Based Jump Logic:
                # If I am older (lower index) than the other connection, I go straight (don't detect intersection).
                if self in other_connections:
                     my_index = other_connections.index(self)
                     # other is guaranteed to be in other_connections because we are iterating it
                     other_index = other_connections.index(other) # No try/except needed hopefully
                     
                     if my_index < other_index:
                         continue
                # iterate other's segments
                # We use raw points from other.path to be robust
                if not other.path: continue
                for j in range(len(other.path) - 1):
                    op1 = other.path[j]
                    op2 = other.path[j+1]
                    other_seg = QLineF(op1, op2)
                    
                    # Intersect?
                    intersection_point = QPointF()
                    type_ = current_seg.intersect(other_seg, intersection_point)
                    
                    if type_ == QLineF.BoundedIntersection:
                        # Check if it's a real crossing, not just touching endpoints
                        # and not collinear overlaps
                        dist = math.sqrt((intersection_point.x() - p1.x())**2 + (intersection_point.y() - p1.y())**2)
                        
                        # Filter out hits too close to start/end of segment (corners)
                        if r < dist < (length - r):
                            intersections.append(dist)

            intersections.sort()
            
            # Build segment with jumps
            current_dist = 0.0
            
            # De-duplicate close intersections (overlapping lines)
            clean_intersections = []
            if intersections:
                last_d = intersections[0]
                clean_intersections.append(last_d)
                for d in intersections[1:]:
                    if d - last_d > 2.2 * r: # Ensure space for jump
                        clean_intersections.append(d)
                        last_d = d

            for dist in clean_intersections:
                # Draw line to jump start
                # jump start is at dist - r
                segment_end_dist = dist - r
                
                if segment_end_dist > current_dist:
                    dest = p1 + u * segment_end_dist
                    self.painter_path.lineTo(dest)
                
                # Draw Jump (Arc)
                # We want a semi-circle. 
                # QPainterPath.arcTo(rect, startAngle, sweepLength)
                # Rect is bounding box of the circle.
                # Center of jump is p1 + u * dist
                jump_center = p1 + u * dist
                
                # Determine rect
                # This arc should bulge "up" relative to the line direction?
                # Standard PFD jump convention: usually bumps 'up' (screen Y negative) for horizontal
                # For vertical, bumps left or right?
                # Let's say we bump "Positive Normal"
                # Normal (-y, x)
                
                rect_top_left = jump_center - QPointF(r, r)
                rect = QRectF(rect_top_left, QSizeF(2*r, 2*r))
                
                # Calculate angle of the line
                angle = math.degrees(math.atan2(u.y(), u.x()))
                # arcTo takes start angle (3 o'clock is 0)
                # We want to start at angle - 180 (backwards) ? No.
                # If moving Right (0 deg), we start at 180 (left side of circle) and sweep -180 (up/ccw?)
                
                # Actually, simpler: 
                # p_start = center - u*r
                # p_end = center + u*r
                
                # If we use arcTo, we need the rect.
                # if Line is Horizontal Right (0 deg)
                # we draw line to left-of-center.
                # We want arc to go UP. 
                # StartAngle 180, Sweep -180 (Clockwise check?)
                # Qt: Positive sweep is Counter-Clockwise.
                # if we want Bump UP, we need start 180, sweep 180? (Goes down?)
                # 0 is East. 90 is North (Screen Y is down, so 90 is Down visually in normal math, but Qt Y is down)
                # Wait, Qt Y is down.
                # 0 = Right (X+)
                # 90 = Down (Y+)
                # 270 = Up (Y-)
                
                # If Horizontal Right: Start 180 (Left), sweep +180 -> goes through 270 (Up). Correct.
                # If Horizontal Left: Angle 180.
                # We approach from Right side of circle (0 deg).
                # Start 0. Sweep -180 -> goes through -90 (Up, which is 270). Correct. (Or +180 goes through 90 Down)
                
                # General Formula:
                # we enter at -u (relative to center).
                # angle of -u is angle + 180.
                # we want to bulge 'Left' relative to direction? Or just always Up/Left?
                # Let's simple fix: always counter-clockwise (+180)
                
                self.painter_path.arcTo(rect, -angle + 180, -180) 
                # Note: Qt angles are counter-clockwise, but Y is flipped.
                # Visual Check required.
                
                current_dist = dist + r
            
            # Draw remaining line
            if current_dist < length:
                self.painter_path.lineTo(p2)


    def paint(self, painter, theme="light", zoom=1.0):
        # Determine visual width based on selection
        visual_width = 4.0 if self.is_selected else 2.5
        
        # Calculate LOGICAL width to maintain constant VISUAL width
        pen_width = visual_width / max(0.1, zoom)

        if self.is_selected:
            color = QColor("#2563eb")
            pen = QPen(color, pen_width)
            brush_color = color
        else:
            color = Qt.white if theme == "dark" else Qt.black
            pen = QPen(color, pen_width)
            brush_color = color

        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        
        # 1. Draw The Path (with jumps)
        # Fallback to simple path if painter_path empty
        if self.painter_path.isEmpty() and self.path:
             for i in range(len(self.path)-1):
                 painter.drawLine(self.path[i], self.path[i+1])
        else:
             painter.drawPath(self.painter_path)

        # 2. Draw Arrow at End
        if len(self.path) >= 2:
            p_end = self.path[-1]
            p_prev = self.path[-2]
            
            # Vector
            vec = p_end - p_prev
            l = math.sqrt(vec.x()**2 + vec.y()**2)
            if l > 0:
                # Normalize
                u = vec / l
                
                # OFFSET THE ARROW TIP
                # Visual padding of component plate is ~6px.
                # 10px visual gap ensures we clear the component plate in Dark Mode.
                # In Light Mode, we only need to clear the grip radius (~4px), or users might prefer it tighter.
                
                visual_retract = 10.0 if theme == "dark" else 4.0
                retract_px = visual_retract / max(0.1, zoom)
                
                if l < retract_px: 
                    retract_px = 0
                
                p_tip = p_end - u * retract_px
                
                # Arrow Geometry
                # Maintain constant VISUAL size for the arrow
                visual_arrow_size = 15.0
                arrow_size = visual_arrow_size / max(0.1, zoom)
                
                # Perpendicular vector (-y, x)
                perp = QPointF(-u.y(), u.x())
                
                p_base = p_tip - u * arrow_size
                
                p1 = p_base + perp * (arrow_size / 2.5)
                p2 = p_base - perp * (arrow_size / 2.5)
                
                arrow_poly = QPolygonF([p_tip, p1, p2])
                
                # Draw Eraser Line to hide the "nose"
                eraser_color = QColor("#0f172a") if theme == "dark" else Qt.white
                
                # Eraser must be slightly thicker than the line to fully cover it
                eraser_width = (visual_width + 1.0) / max(0.1, zoom)
                painter.setPen(QPen(eraser_color, eraser_width))
                painter.drawLine(p_tip, p_end)
                
                # Draw Arrow with High Contrast Black Border
                # Solid Black border ensures visibility on top of EVERYTHING.
                border_width = 1.5 / max(0.1, zoom)
                painter.setPen(QPen(Qt.black, border_width))
                painter.setBrush(QBrush(brush_color))
                painter.drawPolygon(arrow_poly)
                painter.setBrush(Qt.NoBrush) # Reset
                painter.setPen(pen) # Restore pen



    def to_dict(self, component_to_id):
        """
        Serializes connection.
        component_to_id: dict mapping ComponentWidget instance -> int ID
        """
        start_id = component_to_id.get(self.start_component, -1)
        end_id = component_to_id.get(self.end_component, -1)
        
        return {
            "start_id": start_id,
            "start_grip": self.start_grip_index,
            "start_side": self.start_side,
            "end_id": end_id,
            "end_grip": self.end_grip_index,
            "end_side": self.end_side,
            "path_offset": self.path_offset,
            "start_adjust": self.start_adjust,
            "end_adjust": self.end_adjust
        }
