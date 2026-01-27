import { AbsoluteFill } from "remotion";
import { TransitionSeries, linearTiming, springTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { wipe } from "@remotion/transitions/wipe";

import { Scene1Problem } from "./scenes/Scene1Problem";
import { Scene2Solution } from "./scenes/Scene2Solution";
import { Scene3Workflow } from "./scenes/Scene3Workflow";
import { Scene4Comparison } from "./scenes/Scene4Comparison";
import { Scene5GetStarted } from "./scenes/Scene5GetStarted";
import { colors } from "./styles";

const FPS = 30;

// 转场时长配置
const TRANSITION_DURATION = 20; // frames

export const FragoIntro: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: colors.background }}>
      <TransitionSeries>
        {/* 场景 1: 痛点 (4秒) */}
        <TransitionSeries.Sequence durationInFrames={4 * FPS}>
          <Scene1Problem />
        </TransitionSeries.Sequence>

        {/* 转场: 淡入淡出 */}
        <TransitionSeries.Transition
          presentation={fade()}
          timing={springTiming({
            config: { damping: 200 },
            durationInFrames: TRANSITION_DURATION,
          })}
        />

        {/* 场景 2: frago 介绍 (3秒) */}
        <TransitionSeries.Sequence durationInFrames={3 * FPS}>
          <Scene2Solution />
        </TransitionSeries.Sequence>

        {/* 转场: 从右滑入 */}
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({
            config: { damping: 200 },
            durationInFrames: TRANSITION_DURATION,
          })}
        />

        {/* 场景 3: 工作流程 (6秒) */}
        <TransitionSeries.Sequence durationInFrames={6 * FPS}>
          <Scene3Workflow />
        </TransitionSeries.Sequence>

        {/* 转场: 擦除 */}
        <TransitionSeries.Transition
          presentation={wipe({ direction: "from-left" })}
          timing={linearTiming({
            durationInFrames: TRANSITION_DURATION,
          })}
        />

        {/* 场景 4: 效果对比 (4秒) */}
        <TransitionSeries.Sequence durationInFrames={4 * FPS}>
          <Scene4Comparison />
        </TransitionSeries.Sequence>

        {/* 转场: 淡入淡出 */}
        <TransitionSeries.Transition
          presentation={fade()}
          timing={springTiming({
            config: { damping: 200 },
            durationInFrames: TRANSITION_DURATION,
          })}
        />

        {/* 场景 5: 快速开始 (7秒，含充足阅读留白) */}
        <TransitionSeries.Sequence durationInFrames={7 * FPS}>
          <Scene5GetStarted />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </AbsoluteFill>
  );
};
