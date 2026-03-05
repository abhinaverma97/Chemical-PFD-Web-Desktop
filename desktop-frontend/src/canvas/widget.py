import os
from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import Qt, QPoint, QPointF, QRectF, QSize
from PyQt5.QtWidgets import QWidget, QLabel, QUndoStack
from PyQt5.QtWidgets import QWidget, QLabel, QUndoStack, QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QSizePolicy
from PyQt5.QtGui import QPainter, QColor, QPalette

from src.connection import Connection
from src.component_widget import ComponentWidget
import src.app_state as app_state
from src.canvas import resources, painter
from src.canvas.commands import AddCommand, DeleteCommand, MoveCommand, AddConnectionCommand
from src.canvas.validation import GraphValidator


class CanvasWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Canvas background
        self.setObjectName("canvasArea")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

        palette = self.palette()
        palette.setColor(self.backgroundRole(), Qt.white)
        self.setPalette(palette)

        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.undo_stack = QUndoStack(self)

        # State
        self.components = []
        self.connections = []
        self.active_connection = None

        # PROJECT TRACKING
        self.project_id = None
        self.project_name = None

        # Tracks if this is a fresh, unsaved project ---
        self.is_new_project = False
        
        self.file_path = None
        self.is_modified = False
        self.undo_stack.cleanChanged.connect(self.on_undo_stack_changed)
        self.undo_stack.indexChanged.connect(self.run_validation)

        # Configs
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.component_config = resources.load_config(base_dir)
        self.label_data = resources.load_label_data(base_dir)
        self.base_dir = base_dir
        
        self.zoom_level = 1.0
        self.logical_size =  QSize(3000, 2000)
        self.setFixedSize(self.logical_size)

        from src.theme_manager import theme_manager
        theme_manager.theme_changed.connect(self.update_canvas_theme)
        self.update_canvas_theme()
        
        # Validation State
        self.validation_errors = {
            "isolated": [],
            "loops": [],
            "flow_errors": [],
            "missing_inlet": False,
            "missing_outlet": False
        }
        
    def run_validation(self):
        """Re-evaluates the canvas state for graph errors matching PFD rules."""
        validator = GraphValidator(self.components, self.connections)
        result = validator.validate()
        self.validation_errors = result

        # Update component error states
        for comp in self.components:
            comp.is_valid = True
            comp.critical_error = False
            comp.validation_error_msg = ""

            error_msgs = []
            if comp in self.validation_errors["isolated"]:
                comp.is_valid = False
                error_msgs.append("Isolated component (no connections).")
            if comp in self.validation_errors["loops"]:
                comp.is_valid = False
                comp.critical_error = True
                error_msgs.append("Circular loop detected.")
            elif comp in self.validation_errors["flow_errors"]:
                comp.is_valid = False
                comp.critical_error = True
                # Build a specific message depending on which side is broken
                no_inlet  = comp in self.validation_errors.get("unreachable_from_inlet", [])
                no_outlet = comp in self.validation_errors.get("cant_reach_outlet", [])
                if no_inlet and no_outlet:
                    error_msgs.append("No path from any inlet or to any outlet.")
                elif no_inlet:
                    error_msgs.append("No path from any inlet to this component.")
                elif no_outlet:
                    error_msgs.append("No path from this component to any outlet.")

            if error_msgs:
                comp.validation_error_msg = "\n".join(error_msgs)

            comp.update()


        # Trigger re-paint on the main canvas (e.g. for global warning indicators)
        self.update()

    def expand_to_contain(self, rect):
        """Expand logical size if rect is outside current bounds."""
        margin = 500 # Expansion chunk
        new_w = self.logical_size.width()
        new_h = self.logical_size.height()
        expanded = False
        
        if rect.right() > new_w - 100:
            new_w = max(new_w + margin, rect.right() + margin)
            expanded = True
            
        if rect.bottom() > new_h - 100:
            new_h = max(new_h + margin, rect.bottom() + margin)
            expanded = True
            
        if expanded:
            self.logical_size = QSize(int(new_w), int(new_h))
            self.apply_zoom() # Re-applies size with zoom

    def apply_zoom(self):
        """Apply the current zoom level to the canvas size and all components."""
        # Resize the canvas surface
        new_w = int(self.logical_size.width() * self.zoom_level)
        new_h = int(self.logical_size.height() * self.zoom_level)
        self.setFixedSize(new_w, new_h)
        
        # Update all components
        for comp in self.components:
            comp.update_visuals(self.zoom_level)
            
        self.update()

    def zoom_in(self):
        self.zoom_level *= 1.1
        self.apply_zoom()

    def zoom_out(self):
        self.zoom_level /= 1.1
        self.apply_zoom()
        
    def zoom_fit(self):
        if not self.components:
            return
            
        # Calculate bounding box of all LOGICAL rects
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')
        
        for comp in self.components:
            r = comp.logical_rect
            min_x = min(min_x, r.left())
            min_y = min(min_y, r.top())
            max_x = max(max_x, r.right())
            max_y = max(max_y, r.bottom())
            
        # Add some padding
        padding = 50
        content_w = (max_x - min_x) + (padding * 2)
        content_h = (max_y - min_y) + (padding * 2)
        
        # Get viewport size (parent is scroll area's viewport usually, parent.parent is scrollarea)
        viewport = self.parentWidget()
        if not viewport: return
        
        view_w = viewport.width()
        view_h = viewport.height()
        
        # Calculate zoom needed
        zoom_w = view_w / content_w
        zoom_h = view_h / content_h
        
        # Use valid min zoom
        self.zoom_level = min(zoom_w, zoom_h)
        
        # Safety clamp: Fit shouldn't zoom in past 100% usually, or just slightly.
        # User complained it's "too much zoomed into".
        # Let's cap Fit at 1.0 (100%)
        self.zoom_level = max(0.1, min(self.zoom_level, 1.0))
        
        self.apply_zoom()

    def update_canvas_theme(self):
        from src.theme_manager import theme_manager
        current_theme = theme_manager.current_theme
        
        palette = self.palette()
        if current_theme == "dark":
            # Using Slate 900 #0f172a
            color_hex = "#0f172a"
            palette.setColor(self.backgroundRole(), QColor(color_hex))
            self.setStyleSheet(f"QWidget#canvasArea {{ background-color: {color_hex}; }}")
        else:
            palette.setColor(self.backgroundRole(), Qt.white)
            self.setStyleSheet("QWidget#canvasArea { background-color: white; }")
            
        self.setPalette(palette)
        
        # Force repaint of all components to adapt to theme (e.g. background plates)
        for comp in self.components:
            comp.update()
            
        self.update()

    # ---------------------- DRAG & DROP ----------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        import json
        pos = event.pos()
        text = event.mimeData().text()
        
        # Parse JSON component data
        try:
            component_data = json.loads(text)
            object_name = component_data.get('object', text)
            s_no = component_data.get('s_no', '')
            legend = component_data.get('legend', '')
            suffix = component_data.get('suffix', '')
            svg = component_data.get('svg', '')
            parent = component_data.get('parent', '')
        except (json.JSONDecodeError, ValueError):
            # Fallback for old format (plain text)
            object_name = text
            s_no = ''
            legend = ''
            suffix = ''
            svg = ''
            parent = ''
        
        self.create_component_command(object_name, pos, component_data={
            's_no': s_no,
            'legend': legend,
            'suffix': suffix,
            'svg': svg,
            'parent': parent
        })
        event.acceptProposedAction()

    def deselect_all(self):
        for comp in self.components:
            comp.set_selected(False)
        for conn in self.connections:
            conn.is_selected = False
        self.update()

    def start_connection(self, component, grip_index, side):
        """Called by ComponentWidget when a port is clicked."""
        self.deselect_all()
        # Create a new transient connection
        self.active_connection = Connection(component, grip_index, side)
        # Position the end point at the start point initially
        self.active_connection.current_pos = self.active_connection.get_start_pos()
        self.update()

    def get_logical_pos(self, pos):
        """Convert screen (visual) pos to logical pos."""
        return QPointF(pos.x() / self.zoom_level, pos.y() / self.zoom_level)

    # ---------------------- SELECTION + CONNECTION LOGIC ----------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.deselect_all()
            
            # Map click to logical for connection testing
            logical_pos = self.get_logical_pos(event.pos())

            # Connection hit test
            hit_connection = None
            hit_index = -1
            for conn in self.connections:
                # CONNECTION HIT TEST uses LOGICAL coordinates
                # Ensure connection class is updated or we pass logical logic
                idx = conn.hit_test(logical_pos)
                if idx != -1:
                    hit_connection = conn
                    hit_index = idx
                    break

            if hit_connection:
                # Drag logic for connection
                hit_connection.is_selected = True
                self.drag_connection = hit_connection
                self.drag_start_pos = logical_pos # Store LOGICAL start

                best_param = "path_offset"
                best_sensitivity = QPointF(0, 0)
                best_mag_sq = -1

                params = ["path_offset", "start_adjust", "end_adjust"]
                base_points = list(hit_connection.path)

                for p in params:
                    old = getattr(hit_connection, p)
                    setattr(hit_connection, p, old + 1.0)
                    hit_connection.update_path(self.components, self.connections)
                    new_points = hit_connection.path
                    
                    sens = QPointF(0, 0)
                    if hit_index < len(base_points) - 1 and hit_index < len(new_points) - 1:
                        a = (base_points[hit_index] + base_points[hit_index + 1]) / 2
                        b = (new_points[hit_index] + new_points[hit_index + 1]) / 2
                        sens = b - a
                    
                    setattr(hit_connection, p, old)
                    mag = sens.x()**2 + sens.y()**2
                    if mag > best_mag_sq:
                        best_mag_sq = mag
                        best_param = p
                        best_sensitivity = sens
                
                hit_connection.path = list(base_points)
                hit_connection.update_path(self.components, self.connections)

                self.drag_param_name = best_param
                self.drag_sensitivity = best_sensitivity
                self.drag_start_param_val = getattr(hit_connection, best_param)

                self.setFocus()
                self.update()
                event.accept()
                return

        # Check if clicked on a component
        child = self.childAt(event.pos())
        if child:
            curr = child
            while curr and not isinstance(curr, ComponentWidget) and curr != self:
                curr = curr.parentWidget()
            
            if isinstance(curr, ComponentWidget):
                self.drag_item = curr
                self.drag_item_start_pos = curr.pos()

        # Clicked blank
        self.active_connection = None
        self.drag_connection = None
        self.setFocus()
        event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        logical_pos = self.get_logical_pos(event.pos())
        
        if self.active_connection:
            self.update_connection_drag(logical_pos) # Pass logical
            # Don't call super() here because QWidget default doesn't care
            # But sticky notes might? No, they are widgets.
            return super().mouseMoveEvent(event)

        if hasattr(self, "drag_connection") and self.drag_connection:
            delta = logical_pos - self.drag_start_pos
            sens_sq = self.drag_sensitivity.x()**2 + self.drag_sensitivity.y()**2
            
            if sens_sq > 0.001:
                dot = delta.x() * self.drag_sensitivity.x() + delta.y() * self.drag_sensitivity.y()
                change = dot / sens_sq
                new_val = self.drag_start_param_val + change
                setattr(self.drag_connection, self.drag_param_name, new_val)
                self.drag_connection.update_path(self.components, self.connections)
                self.update()

        super().mouseMoveEvent(event)

    def update_connection_drag(self, pos):
        # POS is in LOGICAL coordinates
        if not self.active_connection:
            return

        snap = False
        # Find closest grip
        best_dist = 20.0 # Standard tolerance (Logical)
        best_grip = None

        for comp in self.components:
            # Check bounding box (in logical)
            if not comp.logical_rect.adjusted(-30, -30, 30, 30).contains(pos):
                continue
            
            # Don't snap to start component
            if comp == self.active_connection.start_component:
                continue

            grips = comp.get_grips()
            # Grip positions need to be mapped to logical!
            # comp.get_grip_position returns coordinate relative to Widget (0,0) top left
            # Widget top-left LOGICAL is comp.logical_rect.topLeft()
            # So Global Logical Grip = comp.logical_rect.topLeft() + GripOffset
             
            for i, _ in enumerate(grips):
                # We need the logical grip position relative to component 
                # Since get_grip_position relies on SVG rect which scales...
                # Actually, comp.get_grip_position() returns pixel offsest at current size
                # We need to un-scale it to get logical offset.
                
                visual_grip_pos = comp.get_grip_position(i) # Visual offset
                logical_grip_offset = QPointF(visual_grip_pos.x() / self.zoom_level, visual_grip_pos.y() / self.zoom_level)
                
                center = comp.logical_rect.topLeft() + logical_grip_offset
                
                dist = (pos - center).manhattanLength()
                if dist < best_dist:
                    best_dist = dist
                    best_grip = (comp, i, grips[i]["side"])
                    snap = True

        if snap and best_grip:
            self.active_connection.set_snap_target(best_grip[0], best_grip[1], best_grip[2])


        if not snap:
            self.active_connection.clear_snap_target()
            self.active_connection.current_pos = pos 

        self.active_connection.update_path(self.components, self.connections)
        self.update()

    def mouseReleaseEvent(self, event):
        # Handle release in LOGICAL coords
        logical_pos = self.get_logical_pos(event.pos())
        self.handle_connection_release(logical_pos)
        self.drag_connection = None

        if hasattr(self, 'drag_item') and self.drag_item:
            if self.drag_item.pos() != self.drag_item_start_pos:
                cmd = MoveCommand(self.drag_item, self.drag_item_start_pos, self.drag_item.pos())
                self.undo_stack.push(cmd)
            self.drag_item = None

        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.active_connection:
                self.active_connection = None
                self.update()
            else:
                self.deselect_all()
        elif event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected_components()
        else:
            super().keyPressEvent(event)

    def delete_selected_components(self):
        to_del_comps = [c for c in self.components if c.is_selected]
        to_del_conns = [c for c in self.connections if c.is_selected]

        attached_conns = []
        for i in range(len(self.connections) - 1, -1, -1):
            conn = self.connections[i]
            if (conn.start_component in to_del_comps or 
                conn.end_component in to_del_comps):
                if conn not in to_del_conns and conn not in attached_conns:
                    attached_conns.append(conn)

        all_conns_to_del = to_del_conns + attached_conns

        if to_del_comps or all_conns_to_del:
            cmd = DeleteCommand(self, to_del_comps, all_conns_to_del)
            self.undo_stack.push(cmd)
        
        self.run_validation()
        self.update()

    def handle_connection_release(self, pos):
        if self.active_connection:
            if self.active_connection.snap_component:
                self.active_connection.set_end_grip(
                    self.active_connection.snap_component,
                    self.active_connection.snap_grip_index,
                    self.active_connection.snap_side
                )
                self.active_connection.update_path(self.components, self.connections)
                
                # Use Undo Command
                cmd = AddConnectionCommand(self, self.active_connection)
                self.undo_stack.push(cmd)
            
            self.active_connection = None
            self.run_validation()
            self.update()

    # ---------------------- PAINT EVENT ----------------------
    def paintEvent(self, event):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        
        # Apply Zoom SCALE to painter
        qp.scale(self.zoom_level, self.zoom_level) 
        
        # Calculate LOGICAL visible area
        logical_w = int(self.width() / self.zoom_level)
        logical_h = int(self.height() / self.zoom_level)
        
        painter.draw_grid(qp, logical_w, logical_h, app_state.current_theme)
        
        # Draws connections in logical coords!
        painter.draw_connections(qp, self.connections, self.components, theme=app_state.current_theme, zoom=self.zoom_level)
        painter.draw_active_connection(qp, self.active_connection, theme=app_state.current_theme)

    # ---------------------- COMPONENT CREATION ----------------------
    def create_component_command(self, text, pos, component_data=None):
        component_data = component_data or {}
        
        # 1. Try finding SVG by exact filename (from API)
        svg_file = component_data.get('svg', '')
        parent = component_data.get('parent', '')
        svg = None
        
        if svg_file:
            svg = resources.find_svg_file(svg_file, parent, self.base_dir)
            
        # 2. Fallback to fuzzy search
        if not svg:
            svg = resources.find_svg_path(text, self.base_dir)

        config = resources.get_component_config_by_name(text, self.component_config) or {}
        # Important: Copy config to prevent shared state between same components
        config = config.copy()
        
        # Add API data to config
        config["s_no"] = component_data.get('s_no', '')
        config["object"] = text
        config["legend"] = component_data.get('legend', '')
        config["suffix"] = component_data.get('suffix', '')
        
        # Pass grips from API if available
        # Note: API grips might be JSON string or list. 
        # ComponentWidget handles both in get_grips() "config fallback".
        if component_data.get('grips'):
            config["grips"] = component_data.get('grips')
        
        # Ensure name is set
        if "name" not in config:
            config["name"] = text

        # Label generation
        key = resources.clean_string(text)
        label_text = text

        # Use component_data legend/suffix if available (already in config, but used for logic below)
        legend = component_data.get('legend', '')
        suffix = component_data.get('suffix', '')

        # Auto-initialize label data for new components (Web-Desktop Sync)
        if key not in self.label_data and legend:
            self.label_data[key] = {
                "legend": legend,
                "suffix": suffix,
                "count": 0
            }

        if key in self.label_data:
            d = self.label_data[key]
            d["count"] += 1
            # Override with API/CSV data if available
            legend = legend or d['legend']
            suffix = suffix or d['suffix']
            label_text = f"{legend}{d['count']:02d}{suffix}"

        config["default_label"] = label_text

        if not svg:
            # Check if we should warn
            print(f"[CANVAS WARNING] No SVG found for {text} (File: {svg_file})")
            
            lbl = QLabel(label_text, self)
            # Position at scaled pos
            v_x = int(pos.x() * self.zoom_level)
            v_y = int(pos.y() * self.zoom_level)
            lbl.move(v_x, v_y)
            lbl.setStyleSheet("color:white; background:rgba(255,0,0,0.5); padding:4px; border-radius:4px;")
            lbl.show()
            lbl.adjustSize()
            return

        comp = ComponentWidget(svg, self, config=config)
        # Position incoming (which is visual/drop pos) to LOGICAL
        # Note: dropEvent is in visual.
        logical_pos = QPoint(int(pos.x() / self.zoom_level), int(pos.y() / self.zoom_level))
        
        # Update components logical rect
        comp.logical_rect.moveTo(logical_pos.x(), logical_pos.y())
        comp.update_visuals(self.zoom_level)

        # Auto-Expand
        self.expand_to_contain(comp.logical_rect)
        
        # Add Command uses LOGICAL pos?
        # MoveCommand uses Visual? 
        cmd = AddCommand(self, comp, logical_pos)
        self.undo_stack.push(cmd)
        self.run_validation()
    def export_to_pdf(self, filename):
        from src.canvas.commands import export_pdf
        export_pdf(self, filename)

    def generate_report(self, filename):
        from src.canvas.commands import generate_report
        generate_report(self, filename)

    def export_to_excel(self, filename):
        from src.canvas.commands import export_excel
        export_excel(self, filename)

    # ---------------------- FILE MANAGEMENT ----------------------
    def on_undo_stack_changed(self, clean):
        """
        Called when undo stack clean state changes.
        MANUAL SAVE MODE: Only updates the UI ('*') and is_modified flag.
        Does NOT auto-save to backend.
        """
        print(f"[DEBUG] Stack changed: clean={clean}, project_id={self.project_id}")
        self.is_modified = not clean
        
        # Update window title to show/hide asterisk
        parent = self.parent()
        while parent and not isinstance(parent, QtWidgets.QMdiSubWindow):
            parent = parent.parent()
        
        if parent and hasattr(parent, "setWindowTitle"):
            title = parent.windowTitle()
            # Clean up any existing asterisk first to prevent double **
            base_title = title.rstrip("*")
            
            if not clean:
                parent.setWindowTitle(base_title + "*")
            else:
                parent.setWindowTitle(base_title)

    def save_file(self, filename=None):
        """
        Save canvas to backend. 
        If filename is provided, it's for local PFD export (legacy support).
        """
        if self.project_id:
            # Save to backend
            from src.canvas.export import save_canvas_state
            import src.app_state as app_state
            
            app_state.current_project_id = self.project_id
            app_state.current_project_name = self.project_name
            
            result = save_canvas_state(self)
            if result:
                self.undo_stack.setClean()
                # Mark as "Not New" (Permanent) ---
                self.is_new_project = False
                print(f"[CANVAS] Saved project {self.project_id} to backend")
            return result
        elif filename:
            # Legacy: Save to local PFD file
            from src.canvas.export import save_to_pfd
            save_to_pfd(self, filename)
            self.file_path = filename
            self.undo_stack.setClean()
            return True
        else:
            print("[CANVAS] No project ID or filename for save")
            return False     
           
    def open_file(self, filename):
        """Open local PFD file (legacy support)."""
        from src.canvas.export import load_from_pfd
        return load_from_pfd(self, filename)

    def closeEvent(self, event):
        from src.canvas.commands import handle_close_event
        handle_close_event(self, event)

    def export_to_image(self, filename):
        from src.canvas.commands import export_image
        export_image(self, filename)
