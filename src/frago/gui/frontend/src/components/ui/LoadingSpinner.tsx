interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
}

export default function LoadingSpinner({ size = 'md' }: LoadingSpinnerProps) {
  const sizeMap = {
    sm: 16,
    md: 24,
    lg: 32,
  };

  return (
    <div
      className="spinner"
      style={{
        width: sizeMap[size],
        height: sizeMap[size],
      }}
    />
  );
}
