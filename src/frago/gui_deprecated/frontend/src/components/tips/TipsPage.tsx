import { useState } from 'react';
import { Accordion, AccordionItem } from '../ui/Accordion';
import { openTutorial } from '@/api';
import { ExternalLink, Loader2 } from 'lucide-react';

interface TutorialButtonProps {
  tutorialId: string;
  label?: string;
  anchor?: string;
}

function TutorialButton({ tutorialId, label = 'View Detailed Tutorial', anchor = '' }: TutorialButtonProps) {
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    setLoading(true);
    try {
      const result = await openTutorial(tutorialId, 'auto', anchor);
      if (result.status === 'error') {
        console.error('Failed to open tutorial:', result.error);
      }
    } catch (error) {
      console.error('Failed to open tutorial:', error);
    } finally {
      // Delay resetting loading state for visual feedback
      setTimeout(() => setLoading(false), 500);
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium
                 text-[var(--accent-primary)] bg-[var(--accent-primary)]/10
                 hover:bg-[var(--accent-primary)]/20 rounded-md transition-colors
                 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {loading ? (
        <Loader2 size={14} className="animate-spin" />
      ) : (
        <ExternalLink size={14} />
      )}
      {label}
    </button>
  );
}

export default function TipsPage() {
  return (
    <div className="page-scroll flex flex-col gap-4 h-full">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">Welcome to frago</h1>

      <Accordion>
        <AccordionItem title="Understanding frago" defaultOpen>
          <p className="mb-3">
            You ask AI to extract YouTube subtitles, and it takes 5 minutes to figure it out successfully.
            The next day, you have the same need—it starts from scratch again, completely forgetting how
            it did it yesterday.
          </p>
          <p className="mb-3">
            Even powerful tools like Claude Code can be clumsy when facing everyone's unique task requirements:
            they have to explore from scratch every time, burning tokens each time, and maybe only 5 out of
            10 attempts take the right path.
          </p>
          <p>
            frago solves this problem: explore once, record the process, and solidify it into a reusable recipe.
            Next time you have the same task, call it directly without repeating the exploration. AI is smart enough,
            but not yet "experienced" enough. frago teaches it to remember how to do things.
          </p>
          <TutorialButton tutorialId="intro" />
        </AccordionItem>

        <AccordionItem title="Key Concepts">
          <p className="mb-3">
            <strong className="text-[var(--text-primary)]">Recipe</strong>
            : A reusable automation script that defines a series of browser operations. Recipes can be
            saved, shared, and executed repeatedly.
          </p>
          <p className="mb-3">
            <strong className="text-[var(--text-primary)]">Task</strong>
            : An instance of recipe execution. Each task has its own running status, logs, and results.
          </p>
          <p>
            <strong className="text-[var(--text-primary)]">Session</strong>
            : A connection to the Chrome browser. A session can execute multiple tasks and share browser
            context (login status, cookies, etc.).
          </p>
          <TutorialButton tutorialId="intro" label="Learn More Concepts" anchor="concepts" />
        </AccordionItem>

        <AccordionItem title="Feature Operations Guide">
          <p className="mb-3">Core workflow of frago:</p>
          <ol className="list-decimal list-inside space-y-1 mb-3">
            <li>Launch Chrome in debug mode</li>
            <li>Create or select a recipe</li>
            <li>Run the recipe and monitor task status</li>
            <li>View results and optimize the recipe</li>
          </ol>
          <TutorialButton tutorialId="guide" />
        </AccordionItem>

        <AccordionItem title="Use Cases and Scenarios">
          <p className="mb-3">frago is suitable for repetitive work that requires web interaction:</p>
          <ul className="list-disc list-inside space-y-1">
            <li>Collect data from multiple websites and organize it into structured formats</li>
            <li>Automatically fill forms and submit applications</li>
            <li>Monitor web page changes and trigger notifications</li>
            <li>Perform UI testing and verify page functionality</li>
            <li>Batch download files or images</li>
          </ul>
          <TutorialButton tutorialId="intro" label="View Application Scenarios" anchor="use-cases" />
          <TutorialButton tutorialId="best-practices" label="Best Practices Guide" />
        </AccordionItem>

        <AccordionItem title="Video Tutorials">
          <p className="mb-3">
            Get started with frago quickly through video tutorials, including beginner's guides,
            advanced tips, and practical examples.
          </p>
          <TutorialButton tutorialId="videos" label="Browse Video Tutorials" />
        </AccordionItem>

        <AccordionItem title="Quick Start">
          <ol className="list-decimal list-inside space-y-2">
            <li>
              Ensure Chrome is launched with debugging mode enabled (
              <code className="font-mono text-sm bg-[var(--bg-subtle)] px-1.5 py-0.5 rounded">
                --remote-debugging-port=9222
              </code>
              )
            </li>
            <li>
              Create a new recipe or import an existing one on the{' '}
              <strong className="text-[var(--text-primary)]">Recipes</strong> page
            </li>
            <li>
              Select a recipe, click run, and view execution progress on the{' '}
              <strong className="text-[var(--text-primary)]">Tasks</strong> page
            </li>
          </ol>
          <TutorialButton tutorialId="guide" label="View Complete Guide" />
        </AccordionItem>
      </Accordion>
    </div>
  );
}
