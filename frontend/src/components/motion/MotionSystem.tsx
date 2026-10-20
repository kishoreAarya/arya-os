import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';

/**
 * Hook to detect whether the user requested reduced motion
 */
export function usePrefersReducedMotion(): boolean {
  const [prefersReduced, setPrefersReduced] = useState<boolean>(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handleChange = () => setPrefersReduced(mediaQuery.matches);
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  return prefersReduced;
}

/**
 * Reusable Motion Transition Presets
 */
export const motionPresets = {
  page: {
    initial: { opacity: 0, y: 8 },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: -8 },
    transition: { duration: 0.2, ease: 'easeOut' as const },
  },
  panel: {
    initial: { opacity: 0, scale: 0.985, y: 10 },
    animate: { opacity: 1, scale: 1, y: 0 },
    transition: { duration: 0.25, ease: 'easeOut' as const },
  },
  fadeOnly: {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    transition: { duration: 0.18, ease: 'easeOut' as const },
  },
};

interface MotionViewWrapperProps {
  children: React.ReactNode;
  viewKey: string;
  style?: React.CSSProperties;
  className?: string;
}

/**
 * Wrapper for view transitions respecting prefers-reduced-motion
 */
export const MotionViewWrapper: React.FC<MotionViewWrapperProps> = ({
  children,
  viewKey,
  style,
  className,
}) => {
  const reducedMotion = usePrefersReducedMotion();

  if (reducedMotion) {
    return (
      <div key={viewKey} style={style} className={className}>
        {children}
      </div>
    );
  }

  return (
    <motion.div
      key={viewKey}
      initial={motionPresets.page.initial}
      animate={motionPresets.page.animate}
      exit={motionPresets.page.exit}
      transition={motionPresets.page.transition}
      style={style}
      className={className}
    >
      {children}
    </motion.div>
  );
};

export { AnimatePresence, motion };
