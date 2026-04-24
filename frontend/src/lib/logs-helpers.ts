import type { LogLevel } from "./types";

export function levelColor(level: LogLevel): string {
  switch (level) {
    case "ERROR":
      return "bg-destructive/20 text-destructive ring-1 ring-destructive/30";
    case "WARNING":
      return "bg-warning/20 text-warning ring-1 ring-warning/30";
    case "INFO":
      return "bg-primary/15 text-primary ring-1 ring-primary/25";
    case "DEBUG":
      return "bg-muted text-muted-foreground ring-1 ring-border";
  }
}

export function levelTextColor(level: LogLevel): string {
  switch (level) {
    case "ERROR":
      return "text-destructive";
    case "WARNING":
      return "text-warning";
    case "INFO":
      return "text-primary";
    case "DEBUG":
      return "text-muted-foreground";
  }
}
