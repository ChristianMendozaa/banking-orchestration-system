'use client'

import { cn } from '@/lib/utils'
import { ButtonHTMLAttributes, forwardRef } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
type Size = 'sm' | 'md' | 'lg' | 'xl'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
}

const variantClasses: Record<Variant, string> = {
  primary: 'bg-[#1168BD] text-white hover:bg-[#0d56a0] active:bg-[#0a4280]',
  secondary: 'bg-white text-[#1168BD] border-2 border-[#1168BD] hover:bg-blue-50 active:bg-blue-100',
  danger: 'bg-red-600 text-white hover:bg-red-700 active:bg-red-800',
  ghost: 'bg-transparent text-white border-2 border-white/40 hover:bg-white/10 active:bg-white/20',
}

const sizeClasses: Record<Size, string> = {
  sm: 'py-1.5 px-3 text-sm rounded-lg',
  md: 'py-2 px-4 text-base rounded-xl',
  lg: 'py-3 px-6 text-lg rounded-xl',
  xl: 'py-5 px-10 text-2xl rounded-2xl',
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', className, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center gap-2 font-semibold transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-[#1168BD] focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer select-none',
          variantClasses[variant],
          sizeClasses[size],
          className,
        )}
        {...props}
      >
        {children}
      </button>
    )
  }
)

Button.displayName = 'Button'

export { Button }
