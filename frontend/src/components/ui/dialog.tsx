"use client";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogClose = DialogPrimitive.Close;

function DialogPortal({ children }: { children: React.ReactNode }) {
  return <DialogPrimitive.Portal>{children}</DialogPrimitive.Portal>;
}

function DialogOverlay({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Backdrop>) {
  return (
    <DialogPrimitive.Backdrop
      data-slot="dialog-overlay"
      className={cn(
        "fixed inset-0 z-50 bg-black/50 backdrop-blur-sm",
        "data-[open]:animate-in data-[open]:fade-in-0",
        "data-[closed]:animate-out data-[closed]:fade-out-0",
        className
      )}
      {...props}
    />
  );
}

function DialogContent({
  className,
  children,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Popup>) {
  // M6: lock body scroll when open
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Popup
        data-slot="dialog-content"
        className={cn(
          // M6: max-height 90dvh with internal scroll; close button always visible
          "fixed left-[50%] top-[50%] z-50 flex flex-col w-full max-w-lg translate-x-[-50%] translate-y-[-50%]",
          "max-h-[90dvh] bg-background shadow-xl rounded-2xl border border-border overflow-hidden",
          "data-[open]:animate-in data-[open]:fade-in-0 data-[open]:zoom-in-95 data-[open]:slide-in-from-left-1/2 data-[open]:slide-in-from-top-48%",
          "data-[closed]:animate-out data-[closed]:fade-out-0 data-[closed]:zoom-out-95 data-[closed]:slide-out-to-left-1/2 data-[closed]:slide-out-to-top-48%",
          className
        )}
        {...props}
      >
        {/* Sticky close button header */}
        <div className="flex-shrink-0 flex items-center justify-end px-4 pt-4">
          <DialogPrimitive.Close className="rounded-sm text-muted-foreground hover:text-foreground transition-colors focus:outline-none focus:ring-2 focus:ring-ring">
            <X size={16} />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        </div>
        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto p-6 pt-2 gap-4 flex flex-col">
          {children}
        </div>
      </DialogPrimitive.Popup>
    </DialogPortal>
  );
}

function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-1.5 text-center sm:text-left", className)}
      {...props}
    />
  );
}

function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)}
      {...props}
    />
  );
}

function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("text-base font-semibold leading-none tracking-tight", className)}
      {...props}
    />
  );
}

function DialogDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
};
