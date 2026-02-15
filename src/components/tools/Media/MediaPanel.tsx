import React from "react";
import { ComfyPanel } from "../../ComfyPanel";

export function MediaPanel(props: { comfy: any; isBusy: boolean }) {
  return <ComfyPanel comfy={props.comfy} isBusy={props.isBusy} />;
}
