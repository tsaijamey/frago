import type { LucideIcon } from 'lucide-react';

interface ExampleCardProps {
  icon: LucideIcon;
  title: string;
  description: string;
  onClick: () => void;
}

export default function ExampleCard({
  icon: Icon,
  title,
  description,
  onClick,
}: ExampleCardProps) {
  return (
    <button type="button" className="example-card" onClick={onClick}>
      <div className="example-card-icon">
        <Icon size={20} />
      </div>
      <div className="example-card-title">{title}</div>
      <div className="example-card-description">{description}</div>
    </button>
  );
}
