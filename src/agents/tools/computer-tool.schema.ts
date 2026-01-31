// @ts-ignore: editor may not have deps installed
import { Type } from "@sinclair/typebox";

import { optionalStringEnum, stringEnum } from "../schema/typebox.js";

const COMPUTER_TOOL_ACTIONS = ["status", "snapshot", "act"] as const;

const COMPUTER_ACT_KINDS = [
  "click",
  "double_click",
  "right_click",
  "move",
  "drag",
  "scroll",
  "type",
  "press",
  "hotkey",
  "wait",
] as const;

const COMPUTER_SCROLL_DIRECTIONS = ["vertical", "horizontal"] as const;
const COMPUTER_COORD_METHODS = ["manual", "ocr", "prediction"] as const;

const ComputerActSchema = Type.Object({
  kind: stringEnum(COMPUTER_ACT_KINDS),
  // coordinate inputs
  x: Type.Optional(Type.Number()),
  y: Type.Optional(Type.Number()),
  endX: Type.Optional(Type.Number()),
  endY: Type.Optional(Type.Number()),
  durationMs: Type.Optional(Type.Number()),
  // scroll
  scrollAmount: Type.Optional(Type.Number()),
  scrollDirection: optionalStringEnum(COMPUTER_SCROLL_DIRECTIONS),
  // keyboard
  text: Type.Optional(Type.String()),
  key: Type.Optional(Type.String()),
  keys: Type.Optional(Type.Array(Type.String())),
  // waits
  waitMs: Type.Optional(Type.Number()),
  // coordinate resolution hints
  find_coordinates_by: optionalStringEnum(COMPUTER_COORD_METHODS),
  ocr_text: Type.Optional(Type.String()),
  description: Type.Optional(Type.String()),
  model_name: Type.Optional(Type.String()),
});

export const ComputerToolSchema = Type.Object({
  action: stringEnum(COMPUTER_TOOL_ACTIONS),
  request: Type.Optional(ComputerActSchema),
  delayMs: Type.Optional(Type.Number()),
  timeoutMs: Type.Optional(Type.Number()),
});
