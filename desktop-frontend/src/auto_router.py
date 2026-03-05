"""
Smart Auto-Routing Algorithm for Chemical PFD Editor
Implements orthogonal routing with obstacle avoidance using BFS pathfinding.

Features:
- Grid-based logical coordinate system with configurable resolution
- Obstacle detection for component bounding rectangles
- Existing connection path blocking
- BFS-based shortest orthogonal path computation
- Dynamic re-routing when components move
- Clean orthogonal path generation (H/V segments only)
"""

from collections import deque
from typing import List, Tuple, Set, Dict, Optional
from PyQt5.QtCore import QPointF, QRectF, QPoint
from PyQt5.QtGui import QPainterPath


class GridPoint:
    """Represents a point in the logical grid."""
    
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y
    
    def __eq__(self, other):
        if not isinstance(other, GridPoint):
            return False
        return self.x == other.x and self.y == other.y
    
    def __hash__(self):
        return hash((self.x, self.y))
    
    def __repr__(self):
        return f"GridPoint({self.x}, {self.y})"
    
    def to_qpointf(self, scale: float = 1.0) -> QPointF:
        """Convert grid point to QPointF with optional scaling."""
        return QPointF(self.x * scale, self.y * scale)


class GridObstacle:
    """Represents a rectangular obstacle on the grid."""
    
    def __init__(self, grid_rect: Tuple[int, int, int, int]):
        """
        Initialize obstacle with grid coordinates.
        Args:
            grid_rect: Tuple of (x, y, width, height) in grid units
        """
        self.x, self.y, self.width, self.height = grid_rect
    
    def contains(self, grid_x: int, grid_y: int) -> bool:
        """Check if grid point is inside this obstacle."""
        return (self.x <= grid_x < self.x + self.width and
                self.y <= grid_y < self.y + self.height)
    
    def __repr__(self):
        return f"GridObstacle(x={self.x}, y={self.y}, w={self.width}, h={self.height})"


class AutoRouter:
    """
    Smart orthogonal routing engine using BFS pathfinding.
    
    Grid-based approach:
    - Scene is divided into a logical grid
    - Each grid cell is either passable or blocked
    - BFS finds shortest path from start to end
    - Path is reconstructed and converted to orthogonal segments
    """
    
    # Grid resolution in pixels (higher = coarser grid, faster pathfinding)
    DEFAULT_GRID_RESOLUTION = 10
    
    # Padding around components to avoid collision (in grid units)
    COMPONENT_PADDING = 1  # Reduced to allow tighter routing
    
    # Padding around existing connections (in grid units)
    CONNECTION_PADDING = 1
    
    def __init__(self, grid_resolution: int = DEFAULT_GRID_RESOLUTION):
        """
        Initialize the auto-router.
        
        Args:
            grid_resolution: Size of each grid cell in pixels
        """
        self.grid_resolution = grid_resolution
        self.obstacles: List[GridObstacle] = []
        self.blocked_cells: Set[GridPoint] = set()
        self.existing_path_segments: List[Tuple[QPointF, QPointF]] = []
    
    def clear_obstacles(self):
        """Reset all obstacles and blocked cells."""
        self.obstacles.clear()
        self.blocked_cells.clear()
    
    def add_component_obstacle(self, component_rect: QRectF):
        """
        Add a component bounding rectangle as an obstacle.
        Automatically applies padding.
        
        Args:
            component_rect: QRectF of component logical bounds
        """
        grid_x = int(component_rect.x() / self.grid_resolution)
        grid_y = int(component_rect.y() / self.grid_resolution)
        grid_w = max(1, int(component_rect.width() / self.grid_resolution) + 1)
        grid_h = max(1, int(component_rect.height() / self.grid_resolution) + 1)
        
        # Apply padding
        grid_x -= self.COMPONENT_PADDING
        grid_y -= self.COMPONENT_PADDING
        grid_w += self.COMPONENT_PADDING * 2
        grid_h += self.COMPONENT_PADDING * 2
        
        obstacle = GridObstacle((grid_x, grid_y, grid_w, grid_h))
        self.obstacles.append(obstacle)
    
    def add_connection_obstacle(self, start: QPointF, end: QPointF):
        """
        Add an existing connection segment as an obstacle.
        Creates a thin corridor around the segment.
        
        Args:
            start: Start point of connection segment
            end: End point of connection segment
        """
        start_grid = self._world_to_grid(start)
        end_grid = self._world_to_grid(end)
        
        # Create bounding box around segment
        min_x = min(start_grid.x, end_grid.x)
        max_x = max(start_grid.x, end_grid.x)
        min_y = min(start_grid.y, end_grid.y)
        max_y = max(start_grid.y, end_grid.y)
        
        # Ensure minimum width/height
        if min_x == max_x:
            max_x += 1
        if min_y == max_y:
            max_y += 1
        
        width = max_x - min_x + 1
        height = max_y - min_y + 1
        
        obstacle = GridObstacle((min_x, min_y, width, height))
        self.obstacles.append(obstacle)
    
    def _world_to_grid(self, point: QPointF) -> GridPoint:
        """Convert world coordinates to grid coordinates."""
        grid_x = int(point.x() / self.grid_resolution)
        grid_y = int(point.y() / self.grid_resolution)
        return GridPoint(grid_x, grid_y)
    
    def _is_cell_blocked(self, grid_point: GridPoint) -> bool:
        """Check if a grid cell is blocked by any obstacle."""
        for obstacle in self.obstacles:
            if obstacle.contains(grid_point.x, grid_point.y):
                return True
        return False
    
    def _is_valid_move(self, grid_point: GridPoint, bounds: Optional[QRectF] = None) -> bool:
        """
        Check if a grid cell is valid for pathfinding.
        
        Args:
            grid_point: Grid cell to check
            bounds: Optional world-space bounds to respect
        
        Returns:
            True if cell is passable, False if blocked or out of bounds
        """
        # Check world bounds if provided
        if bounds:
            world_x = grid_point.x * self.grid_resolution
            world_y = grid_point.y * self.grid_resolution
            if not (bounds.x() <= world_x <= bounds.right() and
                    bounds.y() <= world_y <= bounds.bottom()):
                return False
        
        # Check obstacles
        return not self._is_cell_blocked(grid_point)
    
    def find_path(self, start: QPointF, end: QPointF,
                  bounds: Optional[QRectF] = None) -> List[QPointF]:
        """
        Find shortest orthogonal path from start to end using BFS.
        
        Args:
            start: Starting point in world coordinates
            end: Ending point in world coordinates
            bounds: Optional world-space bounds (scene limits)
        
        Returns:
            List of QPointF representing orthogonal path points.
            Returns direct line if no valid path found.
        """
        # Convert to grid coordinates
        start_grid = self._world_to_grid(start)
        end_grid = self._world_to_grid(end)
        
        # If start or end is blocked, try to find nearest valid point
        if self._is_cell_blocked(start_grid):
            start_grid = self._find_nearest_valid_cell(start_grid, bounds)
        if self._is_cell_blocked(end_grid):
            end_grid = self._find_nearest_valid_cell(end_grid, bounds)
        
        # Directional moves: right, left, down, up (orthogonal only)
        directions = [
            (1, 0),   # Right
            (-1, 0),  # Left
            (0, 1),   # Down
            (0, -1),  # Up
        ]
        
        # BFS to find shortest path
        queue = deque([(start_grid, [start_grid])])
        visited: Set[GridPoint] = {start_grid}
        parent_map: Dict[GridPoint, GridPoint] = {}
        
        while queue:
            current, path = queue.popleft()
            
            # Goal reached
            if current == end_grid:
                return self._grid_path_to_world(path)
            
            # Explore neighbors
            for dx, dy in directions:
                neighbor = GridPoint(current.x + dx, current.y + dy)
                
                # Skip if already visited
                if neighbor in visited:
                    continue
                
                # Skip if not valid
                if not self._is_valid_move(neighbor, bounds):
                    continue
                
                visited.add(neighbor)
                parent_map[neighbor] = current
                new_path = path + [neighbor]
                queue.append((neighbor, new_path))
        
        # No path found, return simple orthogonal fallback
        # Create L-shaped path instead of diagonal
        mid_point = QPointF((start.x() + end.x()) / 2, start.y())
        return [start, mid_point, QPointF((start.x() + end.x()) / 2, end.y()), end]
    
    def _find_nearest_valid_cell(self, grid_point: GridPoint,
                                 bounds: Optional[QRectF] = None) -> GridPoint:
        """
        Find nearest valid (non-blocked) grid cell to given point.
        Uses expanding square search.
        
        Args:
            grid_point: Starting grid point
            bounds: Optional bounds to respect
        
        Returns:
            Valid grid point (or original if all invalid)
        """
        if self._is_valid_move(grid_point, bounds):
            return grid_point
        
        # Expanding square search
        for radius in range(1, 20):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    # Only check cells on the perimeter of the square
                    if abs(dx) != radius and abs(dy) != radius:
                        continue
                    
                    neighbor = GridPoint(grid_point.x + dx, grid_point.y + dy)
                    if self._is_valid_move(neighbor, bounds):
                        return neighbor
        
        # Fallback to original point
        return grid_point
    
    def _grid_path_to_world(self, grid_path: List[GridPoint]) -> List[QPointF]:
        """
        Convert grid-based path to world coordinates and simplify.
        
        Args:
            grid_path: List of GridPoint from pathfinding
        
        Returns:
            List of QPointF with optimized path
        """
        if not grid_path:
            return []
        
        # Convert to world coordinates
        world_path = [point.to_qpointf(self.grid_resolution) for point in grid_path]
        
        # Simplify path: remove redundant intermediate points
        # Keep only direction changes
        simplified = [world_path[0]]
        
        for i in range(1, len(world_path) - 1):
            prev_point = world_path[i - 1]
            curr_point = world_path[i]
            next_point = world_path[i + 1]
            
            # Check if current point is a direction change
            is_horizontal_to_vertical = (
                abs(prev_point.x() - curr_point.x()) > 0.1 and  # Prev was horizontal
                abs(curr_point.y() - next_point.y()) > 0.1        # Next is vertical
            )
            
            is_vertical_to_horizontal = (
                abs(prev_point.y() - curr_point.y()) > 0.1 and  # Prev was vertical
                abs(curr_point.x() - next_point.x()) > 0.1        # Next is horizontal
            )
            
            # Keep point if it's a direction change
            if is_horizontal_to_vertical or is_vertical_to_horizontal:
                simplified.append(curr_point)
        
        # Add end point
        if len(world_path) > 1:
            simplified.append(world_path[-1])
        
        return simplified
    
    def build_painter_path(self, path_points: List[QPointF],
                          start_offset: float = 0.0,
                          end_offset: float = 0.0) -> QPainterPath:
        """
        Build a QPainterPath from orthogonal path points.
        
        Args:
            path_points: List of QPointF points
            start_offset: Offset from start point
            end_offset: Offset to end point
        
        Returns:
            QPainterPath with line segments
        """
        if not path_points:
            return QPainterPath()
        
        painter_path = QPainterPath()
        
        if len(path_points) == 1:
            # Single point, create a small path
            painter_path.moveTo(path_points[0])
            painter_path.lineTo(path_points[0])
            return painter_path
        
        # Start from first point with offset if specified
        start = path_points[0]
        if start_offset > 0 and len(path_points) > 1:
            # Move along first segment by offset amount
            next_point = path_points[1]
            direction = next_point - start
            distance = (direction.x()**2 + direction.y()**2)**0.5
            if distance > 0:
                normalized = QPointF(direction.x() / distance, direction.y() / distance)
                start = start + normalized * start_offset
        
        painter_path.moveTo(start)
        
        # Draw line segments
        for i in range(1, len(path_points)):
            target = path_points[i]
            
            # Apply end offset to last segment
            if i == len(path_points) - 1 and end_offset > 0:
                prev_point = path_points[i - 1]
                direction = target - prev_point
                distance = (direction.x()**2 + direction.y()**2)**0.5
                if distance > 0:
                    normalized = QPointF(direction.x() / distance, direction.y() / distance)
                    target = target - normalized * end_offset
            
            painter_path.lineTo(target)
        
        return painter_path
    
    def add_jump_overs(self, painter_path: QPainterPath,
                      existing_segments: List[Tuple[QPointF, QPointF]],
                      jump_height: float = 10.0) -> QPainterPath:
        """
        Add visual jump-overs where path crosses existing connections.
        
        Args:
            painter_path: Original painter path
            existing_segments: List of existing connection segments
            jump_height: Height of the jump-over arc
        
        Returns:
            Modified QPainterPath with jumps
        """
        # This is a placeholder for jump-over implementation
        # For now, return the original path
        # TODO: Implement proper arc drawing for crossings
        return painter_path


class RouterCache:
    """
    Cache for router state to avoid redundant calculations.
    Tracks which components/connections have changed.
    """
    
    def __init__(self):
        self.last_router_state = None
        self.last_scene_bounds = None
        self.component_positions: Dict[int, QPointF] = {}
        self.component_rects: Dict[int, QRectF] = {}
    
    def has_changes(self, components: List, bounds: QRectF) -> bool:
        """
        Check if any component positions or scene bounds have changed.
        
        Args:
            components: List of components
            bounds: Current scene bounds
        
        Returns:
            True if state has changed since last cache
        """
        if self.last_scene_bounds != bounds:
            return True
        
        for comp in components:
            comp_id = id(comp)
            if comp_id not in self.component_positions:
                return True
            if self.component_positions[comp_id] != comp.pos():
                return True
        
        return False
    
    def update_state(self, components: List, bounds: QRectF):
        """Update cached state."""
        self.last_scene_bounds = bounds
        self.component_positions.clear()
        self.component_rects.clear()
        
        for comp in components:
            comp_id = id(comp)
            self.component_positions[comp_id] = comp.pos()
            if hasattr(comp, 'logical_rect'):
                self.component_rects[comp_id] = comp.logical_rect
