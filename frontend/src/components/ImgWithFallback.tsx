import { useEffect, useState } from 'react';
import { FileImageOutlined } from '@ant-design/icons';

/**
 * 带占位的图片组件：
 * - url 为空或加载失败时显示灰色占位块（16:9 由外层控制高度）
 */
export default function ImgWithFallback({
  src,
  alt,
  style,
  className,
}: {
  src?: string | null;
  alt?: string;
  style?: React.CSSProperties;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  // src 变化时重置失败状态（如缩略图从占位替换为真实图）
  useEffect(() => {
    setFailed(false);
  }, [src]);

  if (!src || failed) {
    return (
      <div
        className={className}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#f0f2f5',
          color: '#bfbfbf',
          width: '100%',
          height: '100%',
          ...style,
        }}
      >
        <FileImageOutlined style={{ fontSize: 24 }} />
      </div>
    );
  }
  return (
    <img
      className={className}
      src={src}
      alt={alt ?? ''}
      style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block', ...style }}
      onError={() => setFailed(true)}
      loading="lazy"
    />
  );
}
