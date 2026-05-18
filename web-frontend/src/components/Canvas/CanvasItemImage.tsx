import { useEffect, useRef } from "react";
import {
  Image as KonvaImage,
  Transformer,
  Circle,
  Group,
  Text,
} from "react-konva";
import useImage from "use-image";
import Konva from "konva";
import { Rect } from "react-konva";

import { calculateAspectFit } from "../../utils/layout";

import { CanvasItem, CanvasItemImageProps } from "./types";

const LABEL_OFFSET = 4;

export const CanvasItemImage = ({
  item,
  isSelected,
  isInvalid,
  onSelect,
  onChange,
  onDragEnd,
  onTransformEnd,
  stageScale = 1,
  onGripMouseDown,
  onGripMouseEnter,
  onGripMouseLeave,
  isDrawingConnection = false,
  hoveredGrip = null,
}: CanvasItemImageProps) => {
  const [image] = useImage(item.svg || item.icon, "anonymous");

  const groupRef = useRef<Konva.Group>(null);
  const trRef = useRef<Konva.Transformer>(null);
  // Track Shift key state via a ref so we can read it inside boundBoxFunc
  // without changing Konva's strict 2-arg boundBoxFunc signature.
  const shiftHeldRef = useRef(false);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => { shiftHeldRef.current = e.shiftKey; };
    const onKeyUp   = (e: KeyboardEvent) => { shiftHeldRef.current = e.shiftKey; };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup",   onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup",   onKeyUp);
    };
  }, []);

  useEffect(() => {
    if (isSelected && trRef.current && groupRef.current) {
      trRef.current.nodes([groupRef.current]);
      trRef.current.getLayer()?.batchDraw();
    }
  }, [isSelected, item.width, item.height, item.x, item.y, item.rotation]);

  const handleDragEnd = (e: Konva.KonvaEventObject<DragEvent>) => {
    const updatedItem = {
      ...item,
      x: e.target.x(),
      y: e.target.y(),
    };

    onChange(updatedItem);
    onDragEnd?.(updatedItem);
  };

  const handleTransformEnd = () => {
    const node = groupRef.current;

    if (!node) return;

    const scaleX = node.scaleX();
    const scaleY = node.scaleY();

    // Reset Konva's internal scale back to 1 — we store true pixel dimensions
    node.scaleX(1);
    node.scaleY(1);

    // Zoom-aware 20px logical minimum: at zoom 0.5 the threshold is 40 screen px
    const MIN_PX = 20 / (stageScale > 0 ? stageScale : 1);

    const updatedItem: CanvasItem = {
      ...item,
      x: node.x(),
      y: node.y(),
      width: Math.max(MIN_PX, item.width * Math.abs(scaleX)),
      height: Math.max(MIN_PX, item.height * Math.abs(scaleY)),
      rotation: node.rotation(),
    };

    // ① Fire the commit callback FIRST so Editor.tsx can push ONE undo snapshot.
    //    (onTransformEnd is only called at drag-end, not on every pixel moved.)
    onTransformEnd?.(updatedItem);

    // ② Also update visual state so grips / labels reposition immediately.
    onChange(updatedItem);
  };

  const labelText = item.label || item.name;

  const labelX = item.x;
  const labelY = item.y + item.height + LABEL_OFFSET;

  // Calculate aspect-fit dimensions using shared helper
  const {
    x: renderX,
    y: renderY,
    width: renderWidth,
    height: renderHeight,
  } = calculateAspectFit(
    item.width,
    item.height,
    image?.naturalWidth || item.naturalWidth,
    image?.naturalHeight || item.naturalHeight,
  );

  // Sync natural dimensions to item state for routing
  useEffect(() => {
    if (
      image &&
      (image.naturalWidth !== item.naturalWidth ||
        image.naturalHeight !== item.naturalHeight)
    ) {
      onChange({
        ...item,
        naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight,
      });
    }
  }, [image, item.naturalWidth, item.naturalHeight, onChange, item]);

  return (
    <>
      {/* ================= IMAGE (Selectable / Transformable) ================= */}
      <Group
        ref={groupRef}
        draggable
        height={item.height}
        rotation={item.rotation}
        scaleX={1}
        scaleY={1}
        width={item.width}
        x={item.x}
        y={item.y}
        onDragEnd={handleDragEnd}
        onTransformEnd={handleTransformEnd}
      >
        {isInvalid && (
          <Rect
            dash={[6, 4]}
            height={item.height}
            stroke="red"
            strokeWidth={2}
            width={item.width}
          />
        )}
        <KonvaImage
          height={renderHeight}
          image={image || undefined}
          width={renderWidth}
          x={renderX}
          y={renderY}
          onClick={(e) => onSelect(e as any)}
          onTap={(e) => onSelect(e as any)}
        />
      </Group>

      {/* ================= LABEL (Visual Only, Behind Everything) ================= */}

      <Text
        align="center"
        fill="#374151"
        fontFamily="Arial, sans-serif"
        fontSize={12}
        listening={false}
        offsetX={(item.width + 100) / 2} // Center align
        text={labelText}
        width={item.width + 100} // Increase width to prevent wrapping
        x={labelX + item.width / 2}
        y={labelY + 2}
      />

      {/* ================= TRANSFORMER ================= */}
      {isSelected && (
        <Transformer
          ref={trRef}
          boundBoxFunc={(oldBox, newBox) => {
            // Zoom-aware 20px logical minimum
            const MIN = 20 / (stageScale > 0 ? stageScale : 1);

            // Shift key → lock aspect ratio regardless of which handle is dragged
            if (shiftHeldRef.current) {
              const ratio = oldBox.width / oldBox.height;
              const dw = Math.abs(newBox.width - oldBox.width);
              const dh = Math.abs(newBox.height - oldBox.height);
              if (dw >= dh) {
                newBox = { ...newBox, height: newBox.width / ratio };
              } else {
                newBox = { ...newBox, width: newBox.height * ratio };
              }
            }

            // Enforce minimum — revert if either dimension would go below 20px
            if (newBox.width < MIN || newBox.height < MIN) {
              return oldBox;
            }

            return newBox;
          }}
          enabledAnchors={[
            "top-left",
            "top-center",
            "top-right",
            "middle-left",
            "middle-right",
            "bottom-left",
            "bottom-center",
            "bottom-right",
          ]}
          flipEnabled={false}   // Prevent negative-scale artifacts
          keepRatio={false}     // Ratio is controlled manually via Shift in boundBoxFunc
          rotateEnabled={false} // Rotation not needed for PFD components
        />
      )}

      {/* ================= GRIPS (Always On Top) ================= */}
      {(isSelected || isDrawingConnection) &&
        item.grips?.map((grip, index) => {
          // Grips are positioned relative to the RENDERED image, not the container box
          const gripX = item.x + renderX + (grip.x / 100) * renderWidth;
          const gripY =
            item.y + renderY + ((100 - grip.y) / 100) * renderHeight;

          const isHovered =
            hoveredGrip?.itemId === item.id && hoveredGrip?.gripIndex === index;

          return (
            <Circle
              key={index}
              listening
              fill={isHovered ? "#22c55e" : "#3b82f6"}
              opacity={isDrawingConnection && !isSelected ? 0.7 : 1}
              radius={isDrawingConnection ? 6 : 5}
              stroke="#ffffff"
              strokeWidth={isHovered ? 3 : 2}
              x={gripX}
              y={gripY}
              onMouseDown={(e) => {
                e.cancelBubble = true;
                onGripMouseDown?.(item.id, index, gripX, gripY);
              }}
              onMouseEnter={(e) => {
                onGripMouseEnter?.(item.id, index);
                e.target
                  .getStage()
                  ?.container()
                  .style.setProperty("cursor", "pointer");
              }}
              onMouseLeave={(e) => {
                onGripMouseLeave?.();
                e.target
                  .getStage()
                  ?.container()
                  .style.setProperty("cursor", "default");
              }}
            />
          );
        })}
    </>
  );
};
