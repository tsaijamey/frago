import { useTasks } from '@/hooks/useTasks';
import TaskCard from './TaskCard';
import WelcomeScreen from './WelcomeScreen';

export default function TaskList() {
  const { tasks, viewDetail } = useTasks();

  if (tasks.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <WelcomeScreen />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="page-scroll flex flex-col gap-2">
        {tasks.map((task) => (
          <TaskCard
            key={task.session_id}
            task={task}
            onClick={() => viewDetail(task.session_id)}
          />
        ))}
      </div>
    </div>
  );
}
