/**
 * PixelLogo Component
 *
 * Logo.png icon + Pixel-block style lowercase "frago" logo.
 * - Dark mode: pure white
 * - Light mode: pure black
 * - True lowercase letters with ascenders/descenders
 */

interface PixelLogoProps {
  height?: number;
  className?: string;
  showIcon?: boolean; // Whether to show logo.png icon
}

// Letter definition with vertical offset for baseline alignment
interface LetterDef {
  pixels: number[][];
  offsetY: number; // Offset from top (for baseline alignment)
  gapAfter?: number; // Custom gap after this letter (default: letterGap)
}

export default function PixelLogo({ height = 36, className = '', showIcon = true }: PixelLogoProps) {
  // Lowercase letters using single-pixel strokes for visual consistency
  // Each pixel is independent - no adjacent blocks that create "shadow" effect
  // Total grid height is 9 to accommodate ascenders (f) and descenders (g)

  const letters: Record<string, LetterDef> = {
    f: {
      offsetY: 0,
      gapAfter: 0, // No gap - f and r strokes don't overlap
      pixels: [
        [0, 0, 1, 1],
        [0, 1, 0, 0],
        [1, 1, 1, 0],
        [0, 1, 0, 0],
        [0, 1, 0, 0],
        [0, 1, 0, 0],
        [0, 1, 0, 0],
      ],
    },
    r: {
      offsetY: 2,
      gapAfter: 0, // No gap - r and a strokes don't overlap
      pixels: [
        [1, 0, 1, 1],
        [1, 1, 0, 0],
        [1, 0, 0, 0],
        [1, 0, 0, 0],
        [1, 0, 0, 0],
      ],
    },
    a: {
      offsetY: 2,
      pixels: [
        [0, 1, 1, 0],
        [0, 0, 0, 1],
        [0, 1, 1, 1],
        [1, 0, 0, 1],
        [0, 1, 1, 1],
      ],
    },
    g: {
      offsetY: 2, // Same as a, o - closed part aligned
      pixels: [
        [0, 1, 1, 1], // Top arc
        [1, 0, 0, 1],
        [1, 0, 0, 1],
        [1, 0, 0, 1],
        [0, 1, 1, 1], // Closed part bottom (aligned with a, o bottom)
        [0, 0, 0, 1], // Descender from right side
        [0, 1, 1, 0], // Tail - 2 pixels centered
      ],
    },
    o: {
      offsetY: 2,
      pixels: [
        [0, 1, 1, 0],
        [1, 0, 0, 1],
        [1, 0, 0, 1],
        [1, 0, 0, 1],
        [0, 1, 1, 0],
      ],
    },
  };

  const word = 'frago';
  const letterWidth = 4;
  const totalGridHeight = 9; // Full height including ascenders/descenders
  const letterGap = 1.5; // Gap between letters (in pixel units)
  const pixelGap = 0.3; // Gap ratio relative to pixel size
  const blockScale = 1.15; // Scale factor for filled blocks (>1 = larger blocks)

  // Calculate dimensions - pixel size based on height
  const pixelSize = height / (totalGridHeight + pixelGap * (totalGridHeight - 1));
  const actualGap = pixelSize * pixelGap;
  const blockSize = pixelSize * blockScale; // Actual rendered block size
  const blockOffset = (blockSize - pixelSize) / 2; // Center the larger block
  const singleLetterWidth = pixelSize * letterWidth + actualGap * (letterWidth - 1);

  // Calculate cumulative offsets for each letter (respecting custom gapAfter)
  const letterOffsets: number[] = [];
  let cumulativeX = 0;
  for (let i = 0; i < word.length; i++) {
    letterOffsets.push(cumulativeX);
    const char = word[i];
    const letterDef = letters[char];
    const gap = letterDef?.gapAfter ?? letterGap;
    cumulativeX += singleLetterWidth + gap * pixelSize;
  }
  const totalWidth = cumulativeX - (letters[word[word.length - 1]]?.gapAfter ?? letterGap) * pixelSize;

  // Add padding to accommodate scaled blocks that extend beyond original boundaries
  const padding = blockOffset;

  const svgElement = (
    <svg
      width={totalWidth + padding * 2}
      height={height + padding * 2}
      viewBox={`${-padding} ${-padding} ${totalWidth + padding * 2} ${height + padding * 2}`}
      className="pixel-logo"
      aria-label="frago logo"
      role="img"
    >
      {word.split('').map((char, letterIndex) => {
        const letterDef = letters[char];
        if (!letterDef) return null;

        const letterOffsetX = letterOffsets[letterIndex];
        const letterOffsetY = letterDef.offsetY * (pixelSize + actualGap);

        return letterDef.pixels.map((row, y) =>
          row.map((filled, x) =>
            filled ? (
              <rect
                key={`${letterIndex}-${x}-${y}`}
                x={letterOffsetX + x * (pixelSize + actualGap) - blockOffset}
                y={letterOffsetY + y * (pixelSize + actualGap) - blockOffset}
                width={blockSize}
                height={blockSize}
                fill="currentColor"
              />
            ) : null
          )
        );
      })}
    </svg>
  );

  if (!showIcon) {
    return <div className={className}>{svgElement}</div>;
  }

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <img
        src="/icons/logo-64.png"
        alt="frago icon"
        style={{ height: height + padding * 2 }}
        className="object-contain"
      />
      {svgElement}
    </div>
  );
}
