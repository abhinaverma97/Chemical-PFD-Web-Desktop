import os

import json
from PyQt5.QtWidgets import QWidget
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtCore import Qt, QRectF, QPoint, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor

class ComponentWidget(QWidget):
    def __init__(self, svg_path, parent=None, config=None):
        super().__init__(parent)
        self.svg_path = svg_path
        self.config = config or {}
        self.renderer = QSvgRenderer(svg_path)

        # Dynamic size based on SVG dimensions
        default_size = self.renderer.defaultSize()
        w = default_size.width()
        h = default_size.height()

        if w > 0 and h > 0:
            scale = 100.0 / max(w, h)
            new_w = max(20, int(w * scale))
            new_h = max(20, int(h * scale))
        else:
            new_w, new_h = 100, 60

        self.setFixedSize(new_w, new_h)

        self.hover_port = None
        self.is_selected = False
        self.drag_start_global = None
        
        self.rotation_angle = 0
        self.drag_start_positions = {}
        
        # Validation State
        self.is_valid = True
        self.validation_error_msg = ""
        
        # Logical Coordinates (True 100% scale geometry)
        # Initialize from current geometry or valid defaults
        self.logical_rect = QRectF(self.x(), self.y(), new_w, new_h)

        # Cache for grips to prevent file reading lag during paint events
        self._cached_grips = None
        
        # Cache for actual SVG render rectangle
        self._cached_svg_rect = None

        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)
        
        # Allow painting outside widget bounds (ports at edges)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

    def get_content_rect(self):
        """Content rect = the area for SVG rendering, offset by port padding."""
        zoom = 1.0
        if self.parent() and hasattr(self.parent(), "zoom_level"):
            zoom = self.parent().zoom_level
        
        # Offset by port padding so SVG is centered inside padded widget
        pad = int(self.PORT_PAD * zoom)
        
        w = max(1, self.width() - pad * 2)
        h = max(1, self.height() - pad * 2)
        
        # If label is present, we added extra height to the widget in update_visuals.
        # We must subtract that here so the SVG is rendered only in the "component" part,
        # ensuring aspect ratio and grip positions match the logical_rect.
        if self.config.get('default_label'):
             h = max(1, h - self.LABEL_H)

        return QRectF(pad, pad, w, h)
    
    def calculate_svg_rect(self, content_rect):
        """
        Calculate the actual rectangle where SVG will be rendered.
        Updated to preserve aspect ratio instead of stretching.
        """
        default_size = self.renderer.defaultSize()
        svg_w = default_size.width()
        svg_h = default_size.height()
        
        if svg_w <= 0 or svg_h <= 0:
            return QRectF(content_rect)
            
        scale_w = content_rect.width() / svg_w
        scale_h = content_rect.height() / svg_h
        scale = min(scale_w, scale_h)
        
        new_w = svg_w * scale
        new_h = svg_h * scale
        
        x = content_rect.x() + (content_rect.width() - new_w) / 2.0
        y = content_rect.y() + (content_rect.height() - new_h) / 2.0
        
        return QRectF(x, y, new_w, new_h)
    
    def map_svg_to_widget_coords(self, svg_x_percent, svg_y_percent, svg_rect):
        """
        Map percentage coordinates from SVG space to widget screen space.
        
        MATCHES WEB FORMULA (routing.ts:34-35):
          x = renderX + (grip.x / 100) * renderWidth
          y = renderY + ((100 - grip.y) / 100) * renderHeight
        
        Y is ALWAYS inverted: grip.y=100 → top, grip.y=0 → bottom.
        This matches the web frontend convention.
        """
        cx = svg_rect.x() + (svg_x_percent / 100.0) * svg_rect.width()
        cy = svg_rect.y() + ((100.0 - svg_y_percent) / 100.0) * svg_rect.height()
             
        return QPointF(cx, cy)
    
    # _should_invert_y_axis REMOVED — web always inverts Y, so we do too
    



    def load_grips_from_json(self):
        """
        Load grips from grips.json.
        Used for standard components where CSV might be empty or missing grips.
        """
        json_path = os.path.join("ui", "assets", "grips.json")
        
        if not os.path.exists(json_path):
            return None

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            # Match current component name to 'component' field in JSON
            current_name = self.config.get("name", "").strip()

            for entry in data:
                if entry.get("component") == current_name:
                    grips = entry.get("grips")
                    if isinstance(grips, list) and len(grips) > 0:
                        print(f"[JSON] ✓ Loaded grips for {current_name} from grips.json")
                        return grips
                    else:
                        print(f"[JSON] Empty grips for {current_name}")
                        return None
                        
        except Exception as e:
            print("[GRIPS JSON ERROR]", e)
            return None
        
        return None

    def get_grips(self):
        """
        Centralized grip loading with priority:
        1. Config grips (API Data - Source of Truth)
        2. grips.json (Legacy Fallback)
        3. Default fallback grips
        """
        # Return cached value if available (Prevent Lag)
        if self._cached_grips is not None:
            return self._cached_grips
        
        grips = None
        grip_source = None
        
        # 1. Try config first (API Data)
        cfg = self.config.get("grips")
        if isinstance(cfg, str):
            try:
                parsed = json.loads(cfg)
                if isinstance(parsed, list) and len(parsed) > 0:
                    grips = parsed
                    grip_source = "CONFIG"
            except:
                pass
        elif isinstance(cfg, list) and len(cfg) > 0:
            grips = cfg
            grip_source = "CONFIG"

        # 2. If no config grips, check grips.json (Legacy Fallback)
        if grips is None:
            grips = self.load_grips_from_json()
            if grips:
                grip_source = "JSON"

        # 3. Final fallback → default grips
        if grips is None or not isinstance(grips, list) or len(grips) == 0:
            # print(f"[DEFAULT] Using default grips for {self.config.get('name')}")
            grips = [
                {"x": 0, "y": 50, "side": "left"},
                {"x": 100, "y": 50, "side": "right"},
            ]
            grip_source = "DEFAULT"
        
        # Debug: Print what grips were loaded and from where
        # comp_name = self.config.get("name", "Unknown")
        # if grip_source != "CONFIG":
        #    print(f"[GRIP DEBUG] {comp_name} loaded from {grip_source}")

        # Save to cache
        self._cached_grips = grips
        return grips

    def paintEvent(self, event):
        # Update tooltip based on validity
        if not self.is_valid and self.validation_error_msg:
            self.setToolTip(self.validation_error_msg)
        else:
            # We don't want to hide default tooltips if they existed, but currently they are mostly empty
            self.setToolTip(self.config.get("name", ""))
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        content_rect = self.get_content_rect()

        # Calculate actual SVG render rectangle
        svg_rect = self.calculate_svg_rect(content_rect)
        self._cached_svg_rect = svg_rect  # Cache it for grip calculations

        import src.app_state as app_state

        # Render SVG (no opaque background — connections route around components)
        self.renderer.render(painter, svg_rect)

        # Selection Border — drawn INSET so it stays within widget clip rect
        if self.is_selected:
            painter.setPen(QPen(QColor("#60a5fa"), 2.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(svg_rect.adjusted(1, 1, -1, -1), 6, 6)
            
        # Validation Error Icon (Badge)
        if not self.is_valid:
            error_color = QColor("#f87171") if app_state.current_theme == "dark" else QColor("#ef4444")
            painter.setBrush(error_color)
            painter.setPen(Qt.NoPen)
            
            # Position at top-right corner of the SVG rect
            radius = 5.5
            center_x = svg_rect.right() - radius
            center_y = svg_rect.top() + radius
            
            painter.drawEllipse(QPointF(center_x, center_y), radius, radius)
            
            # Draw an exclamation mark inside the circle
            painter.setPen(QPen(Qt.white, 1.5, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(center_x, center_y - 2), QPointF(center_x, center_y + 1))
            painter.drawPoint(QPointF(center_x, center_y + 3))


        # Label (drawn below SVG, within the extra LABEL_H space added by update_visuals)
        if self.config.get('default_label'):
            label_color = Qt.white if app_state.current_theme == "dark" else Qt.black
            painter.setPen(QPen(label_color))
            # Draw label in the reserved bottom strip
            text_rect = QRectF(0, self.height() - self.LABEL_H, self.width(), self.LABEL_H)
            painter.drawText(text_rect, Qt.AlignCenter, self.config['default_label'])

        # Draw Ports using SVG coordinate mapping
        grips = self.get_grips()
        for idx, grip in enumerate(grips):
            self.draw_dynamic_port(painter, grip, idx, svg_rect)

    def draw_dynamic_port(self, painter, grip, idx, svg_rect):
        """Draw port based on SVG viewBox coordinate mapping"""
        pos = self.map_svg_to_widget_coords(grip["x"], grip["y"], svg_rect)
        center = QPoint(int(pos.x()), int(pos.y()))

        radius = 6 if self.hover_port == idx else 4
        color = QColor("#22c55e") if self.hover_port == idx else QColor("cyan")
        
        # Scale radius by zoom level to prevent "giant dots" at low zoom
        zoom = 1.0
        if self.parent() and hasattr(self.parent(), "zoom_level"):
            zoom = self.parent().zoom_level
            
        # Minimum visibility clamp (e.g., don't go below 2px)
        scaled_radius = max(2, int(radius * zoom))
        
        # If zoom is extremely low (< 0.3), maybe hide non-hovered ports?
        # User feedback: "grips only showing" - implying component is gone.
        # But reducing grip size will help clutter.
        
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, scaled_radius, scaled_radius)

    def get_grip_position(self, idx):
        """Get grip position using SVG coordinate mapping"""
        grips = self.get_grips()

        if 0 <= idx < len(grips):
            grip = grips[idx]
            
            # Use cached SVG rect if available, otherwise calculate
            if self._cached_svg_rect:
                svg_rect = self._cached_svg_rect
            else:
                content_rect = self.get_content_rect()
                svg_rect = self.calculate_svg_rect(content_rect)
            
            pos = self.map_svg_to_widget_coords(grip["x"], grip["y"], svg_rect)
            return QPoint(int(pos.x()), int(pos.y()))

        return QPoint(0, 0)

    def get_logical_grip_position(self, idx):
        """
        Get grip position in LOGICAL coordinates (unscaled).
        
        Matches web formula exactly:
          cx = (grip.x / 100) * width
          cy = ((100 - grip.y) / 100) * height
        
        No margins, no offsets — direct percentage of logical size.
        """
        grips = self.get_grips()

        if 0 <= idx < len(grips):
            grip = grips[idx]
            l_w = self.logical_rect.width()
            l_h = self.logical_rect.height()
            
            cx = (grip["x"] / 100.0) * l_w
            cy = ((100.0 - grip["y"]) / 100.0) * l_h
            
            return QPointF(cx, cy)

        return QPointF(0, 0)

    # SELECTION
    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.update()

    # MOUSE PRESS
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:

            # FIRST: CHECK IF CLICKED A PORT – START A CONNECTION
            if self.hover_port is not None:
                if hasattr(self.parent(), "start_connection"):
                    grips = self.get_grips()
                    side = grips[self.hover_port].get("side", "right")
                    self.parent().start_connection(self, self.hover_port, side)
                    self.parent().setFocus()
                    event.accept()
                    return

            # SELECTION HANDLING
            ctrl = bool(event.modifiers() & Qt.ControlModifier)
            if hasattr(self.parent(), "handle_selection"):
                self.parent().handle_selection(self, ctrl)
            else:
                self.is_selected = True
                self.update()

            if self.parent():
                self.parent().setFocus()

            # PREPARE DRAG
            self.drag_start_global = event.globalPos()
            
            # Record start positions for Undo
            if self.parent() and hasattr(self.parent(), "components"):
                self.drag_start_positions = {
                    c: c.pos() for c in self.parent().components if c.is_selected
                }

            event.accept()
        else:
            super().mousePressEvent(event)

    # MOUSE MOVE
    def mouseMoveEvent(self, event):
        # If drawing connection, forward movement to canvas
        if hasattr(self.parent(), "active_connection") and self.parent().active_connection:
            g = self.mapToGlobal(event.pos())
            parent_pos = self.parent().mapFromGlobal(g)
            if hasattr(self.parent(), "update_connection_drag"):
                # Must convert to LOGICAL coordinates for the canvas
                if hasattr(self.parent(), "get_logical_pos"):
                    logical_pos = self.parent().get_logical_pos(parent_pos)
                    self.parent().update_connection_drag(logical_pos)
                else:
                    self.parent().update_connection_drag(parent_pos)
            return

        # PORT HOVER DETECTION using SVG coordinate mapping
        pos = event.pos()
        prev = self.hover_port
        self.hover_port = None

        grips = self.get_grips()
        
        # Use cached SVG rect if available
        if self._cached_svg_rect:
            svg_rect = self._cached_svg_rect
        else:
            content_rect = self.get_content_rect()
            svg_rect = self.calculate_svg_rect(content_rect)

        for idx, grip in enumerate(grips):
            grip_pos = self.map_svg_to_widget_coords(grip["x"], grip["y"], svg_rect)
            center = QPoint(int(grip_pos.x()), int(grip_pos.y()))

            if (pos - center).manhattanLength() < 10:
                self.hover_port = idx
                break

        if prev != self.hover_port:
            self.update()

        # DRAGGING (with threshold to prevent jitter on click)
        if event.buttons() & Qt.LeftButton and self.drag_start_global:
            curr_global = event.globalPos()
            delta = curr_global - self.drag_start_global
            
            # Threshold: ignore micro-movements (prevents "expand" on simple click)
            if delta.manhattanLength() < 3:
                return

            parent = self.parent()
            if parent and hasattr(parent, "components"):
                # move all selected
                for comp in parent.components:
                    if comp.is_selected:
                        # Update LOGICAL position
                        # new_pos is visual. Convert to logical.
                        z = parent.zoom_level if hasattr(parent, "zoom_level") else 1.0
                        
                        # We calculate delta in logical space
                        logical_delta = delta / z
                        
                        # Update logical rect position
                        comp.logical_rect.translate(logical_delta.x(), logical_delta.y())
                        
                        # Update visuals from logical
                        comp.update_visuals(z)
                        
                        # Auto-Expand
                        if hasattr(parent, "expand_to_contain"):
                            parent.expand_to_contain(comp.logical_rect)
                        
                # Recalculate paths for connections attached to moved components
                if hasattr(parent, "connections"):
                    moved = {c for c in parent.components if c.is_selected}
                    for conn in parent.connections:
                        if conn.start_component in moved or conn.end_component in moved:
                            conn.update_path(parent.components, parent.connections)
                        
                # Force full repaint — prevents stale connection artefacts
                parent.repaint()
            else:
                 # Single item move (fallback)
                 z = self.parent().zoom_level if (self.parent() and hasattr(self.parent(), "zoom_level")) else 1.0
                 new_pos = self.pos() + delta
                 
                 # Update logical
                 self.logical_rect.moveTo(new_pos.x() / z, new_pos.y() / z)
                 self.update_visuals(z)
                 
                 if self.parent(): self.parent().repaint()

            self.drag_start_global = curr_global

    # MOUSE RELEASE
    def mouseReleaseEvent(self, event):
        # Forward release during connection building
        if hasattr(self.parent(), "active_connection") and self.parent().active_connection:
            g = self.mapToGlobal(event.pos())
            parent_pos = self.parent().mapFromGlobal(g)
            if hasattr(self.parent(), "handle_connection_release"):
                # Use Logical
                if hasattr(self.parent(), "get_logical_pos"):
                    logical_pos = self.parent().get_logical_pos(parent_pos)
                    self.parent().handle_connection_release(logical_pos)
                else:
                    self.parent().handle_connection_release(parent_pos)
                
        # UNDOABLE MOVE 
        if hasattr(self, "drag_start_positions") and self.drag_start_positions:
            from src.canvas.commands import MoveCommand
            
            stack = self.parent().undo_stack
            moved_items = []
            
            for comp, start_pos in self.drag_start_positions.items():
                if comp.pos() != start_pos:
                    moved_items.append((comp, start_pos, comp.pos()))
            
            if moved_items:
                stack.beginMacro("Move Components")
                for comp, start, end in moved_items:
                    cmd = MoveCommand(comp, start, end)
                    stack.push(cmd)
                stack.endMacro()
            
            self.drag_start_positions = {}


    # ---------------------- SERIALIZATION ----------------------
    # ---------------------- ZOOM LOGIC ----------------------
    PORT_PAD = 6   # extra space around SVG for port circles at edges
    LABEL_H = 20   # extra height for component label below SVG

    def update_visuals(self, zoom_level):
        """Update visual geometry based on logical rect and zoom level."""
        pad = int(self.PORT_PAD * zoom_level)
        v_x = int(self.logical_rect.x() * zoom_level) - pad
        v_y = int(self.logical_rect.y() * zoom_level) - pad
        v_w = int(self.logical_rect.width() * zoom_level) + pad * 2
        v_h = int(self.logical_rect.height() * zoom_level) + pad * 2
        # Add space for label text below the SVG
        if self.config.get('default_label'):
            v_h += self.LABEL_H
        
        # Apply
        self.setFixedSize(v_w, v_h)
        self.move(v_x, v_y)

    # ---------------------- SERIALIZATION ----------------------
    def to_dict(self):
        return {
            "x": int(self.logical_rect.x()),
            "y": int(self.logical_rect.y()),
            "width": int(self.logical_rect.width()),
            "height": int(self.logical_rect.height()),
            "rotation": self.rotation_angle,
            "svg_path": self.svg_path,
            "config": self.config
        }