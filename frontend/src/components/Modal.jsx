import './Modal.css';

export default function Modal({ isOpen, onClose, title, children, width }) {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay animate-fadeIn" onClick={onClose}>
      <div
        className="modal-container card animate-slideUp"
        style={width ? { maxWidth: width } : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <div className="modal-header">
            <h2 className="modal-title">{title}</h2>
            <button className="modal-close btn-icon" onClick={onClose}>✕</button>
          </div>
        )}
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
