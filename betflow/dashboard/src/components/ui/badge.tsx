import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center justify-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium leading-none whitespace-nowrap transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background [&>svg]:size-3',
  {
    variants: {
      variant: {
        // House default: raised surface, hairline border, secondary ink.
        default: 'border-border bg-raised text-ink2',
        outline: 'border-border text-ink2',
        primary: 'border-transparent bg-s1/15 text-s1',
        warning: 'border-transparent bg-warning/15 text-warning',
        critical: 'border-transparent bg-critical/15 text-critical',
        drift: 'border-transparent bg-s2/20 text-s2',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

function Badge({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<'span'> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : 'span'
  return (
    <Comp className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
