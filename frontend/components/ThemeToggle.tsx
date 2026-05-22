'use client';

import { useTheme } from 'next-themes';
import { Sun, Moon } from 'lucide-react';
import { useEffect, useState } from 'react';

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);
  if (!mounted) return <div className="w-8 h-8" />;

  const isDark = theme === 'dark';

  return (
    <button
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      title={isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
      className={`
        relative p-2 rounded-lg border transition-all duration-300
        ${isDark
          ? 'bg-kci-blue/20 border-kci-blue/40 text-kci-orange hover:bg-kci-blue/40'
          : 'bg-kci-orange/10 border-kci-orange/30 text-kci-red hover:bg-kci-orange/20'
        }
      `}
    >
      {isDark
        ? <Sun className="w-3.5 h-3.5" />
        : <Moon className="w-3.5 h-3.5" />
      }
    </button>
  );
}
