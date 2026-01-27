import type { CSSProperties } from "react";
import { loadFont } from "@remotion/google-fonts/Inter";

// 加载 Inter 字体
const { fontFamily: interFont } = loadFont("normal", {
  weights: ["400", "500", "600", "700", "800"],
  subsets: ["latin"],
});

// 加载 JetBrains Mono 用于代码
import { loadFont as loadMonoFont } from "@remotion/google-fonts/JetBrainsMono";
const { fontFamily: monoFont } = loadMonoFont("normal", {
  weights: ["400", "500", "700"],
  subsets: ["latin"],
});

export const fonts = {
  primary: interFont,
  mono: monoFont,
};

// 颜色主题 - 更现代的配色
export const colors = {
  // 主色调 - 紫蓝渐变
  primary: "#6366F1",
  primaryDark: "#4F46E5",
  primaryLight: "#818CF8",

  // 强调色 - 青绿
  accent: "#14B8A6",
  accentLight: "#2DD4BF",
  accentDark: "#0D9488",

  // 警告/对比
  warning: "#F59E0B",
  warningLight: "#FBBF24",
  danger: "#EF4444",

  // 成功
  success: "#10B981",
  successLight: "#34D399",

  // 中性色 - 更深的背景
  background: "#0A0A0F",
  backgroundLight: "#18181B",
  backgroundCard: "#1F1F26",

  // 文字
  text: "#FAFAFA",
  textMuted: "#A1A1AA",
  textDim: "#71717A",

  // 边框/装饰
  border: "#27272A",
  borderLight: "#3F3F46",

  // 特效
  glow: "rgba(99, 102, 241, 0.5)",
  glowAccent: "rgba(20, 184, 166, 0.5)",
};

// 通用样式
export const fullScreen: CSSProperties = {
  width: "100%",
  height: "100%",
  display: "flex",
  flexDirection: "column",
  justifyContent: "center",
  alignItems: "center",
  backgroundColor: colors.background,
  fontFamily: fonts.primary,
  overflow: "hidden",
};

// 渐变文字效果
export const gradientText: CSSProperties = {
  background: `linear-gradient(135deg, ${colors.primary} 0%, ${colors.accent} 50%, ${colors.primaryLight} 100%)`,
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
  backgroundClip: "text",
};

// 发光效果
export const glowEffect = (color: string = colors.primary): CSSProperties => ({
  boxShadow: `0 0 40px ${color}40, 0 0 80px ${color}20`,
});

// Spring 配置
export const springConfigs = {
  smooth: { damping: 200 },
  snappy: { damping: 20, stiffness: 200 },
  bouncy: { damping: 8 },
  heavy: { damping: 15, stiffness: 80, mass: 2 },
  gentle: { damping: 30, stiffness: 120 },
};
