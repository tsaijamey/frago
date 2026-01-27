import { Composition, Folder } from "remotion";
import { FragoIntro } from "./FragoIntro";
import { Scene1Problem } from "./scenes/Scene1Problem";
import { Scene2Solution } from "./scenes/Scene2Solution";
import { Scene3Workflow } from "./scenes/Scene3Workflow";
import { Scene4Comparison } from "./scenes/Scene4Comparison";
import { Scene5GetStarted } from "./scenes/Scene5GetStarted";

// 视频配置
const FPS = 30;
const WIDTH = 1920;
const HEIGHT = 1080;

// 计算总时长:
// 场景: 4 + 3 + 6 + 4 + 7 = 24秒
// 转场: 4个转场 × 20帧 = 80帧 ≈ 2.67秒
// 由于转场是重叠的，实际时长 = 24秒 - 2.67秒 ≈ 21.33秒
// 取 22 秒保险
const TOTAL_DURATION = 22 * FPS;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* 完整介绍视频 */}
      <Composition
        id="FragoIntro"
        component={FragoIntro}
        durationInFrames={TOTAL_DURATION}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
      />

      {/* 单独场景（用于调试） */}
      <Folder name="Scenes">
        <Composition
          id="Scene1-Problem"
          component={Scene1Problem}
          durationInFrames={4 * FPS}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
        <Composition
          id="Scene2-Solution"
          component={Scene2Solution}
          durationInFrames={3 * FPS}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
        <Composition
          id="Scene3-Workflow"
          component={Scene3Workflow}
          durationInFrames={6 * FPS}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
        <Composition
          id="Scene4-Comparison"
          component={Scene4Comparison}
          durationInFrames={4 * FPS}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
        <Composition
          id="Scene5-GetStarted"
          component={Scene5GetStarted}
          durationInFrames={7 * FPS}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
      </Folder>
    </>
  );
};
