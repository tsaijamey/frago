import { useTasks } from '@/hooks/useTasks';
import TaskCard from './TaskCard';
import EmptyState from '@/components/ui/EmptyState';

export default function TaskList() {
  const { tasks, viewDetail } = useTasks();

  if (tasks.length === 0) {
    return (
      <EmptyState
        icon="📋"
        title="暂无任务"
        description="运行 frago run 或 frago recipe run 来创建任务"
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {tasks.map((task) => (
        <TaskCard
          key={task.session_id}
          task={task}
          onClick={() => viewDetail(task.session_id)}
        />
      ))}
    </div>
  );
}
