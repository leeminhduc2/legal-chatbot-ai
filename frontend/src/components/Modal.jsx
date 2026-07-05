import './Modal.css';

export default function Modal({
  isOpen,
  onClose,
  title,
  children,
  width,
  closeDisabled = false,
}) {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay animate-fadeIn" onClick={closeDisabled ? undefined : onClose}>
      <div
        className="modal-container card animate-slideUp"
        style={width ? { maxWidth: width } : undefined}
        onClick={(event) => event.stopPropagation()}
      >
        {title && (
          <div className="modal-header">
            <h2 className="modal-title">{title}</h2>
            <button
              className="modal-close btn-icon"
              onClick={closeDisabled ? undefined : onClose}
              disabled={closeDisabled}
              title={closeDisabled ? 'Save or revert changes first.' : ''}
            >
              x
            </button>
          </div>
        )}
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
