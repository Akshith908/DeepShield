import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { UploadZone } from './UploadZone';

function selectFile(file: File) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

describe('UploadZone audio availability', () => {
  it('rejects audio uploads while Reality Defender is unavailable', () => {
    const onFileSelect = vi.fn();
    render(<UploadZone onFileSelect={onFileSelect} />);

    selectFile(new File(['audio-bytes'], 'voice.mp3', { type: 'audio/mpeg' }));

    expect(onFileSelect).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/audio analysis is temporarily unavailable/i);
  });

  it('rejects audio by extension when the MIME type is missing', () => {
    const onFileSelect = vi.fn();
    render(<UploadZone onFileSelect={onFileSelect} />);

    selectFile(new File(['audio-bytes'], 'voice.wav', { type: '' }));

    expect(onFileSelect).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/audio analysis is temporarily unavailable/i);
  });

  it('still accepts image uploads', () => {
    const onFileSelect = vi.fn();
    render(<UploadZone onFileSelect={onFileSelect} />);

    const image = new File(['image-bytes'], 'photo.jpg', { type: 'image/jpeg' });
    selectFile(image);

    expect(onFileSelect).toHaveBeenCalledWith(image);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('advertises audio as temporarily unavailable and does not accept it', () => {
    render(<UploadZone onFileSelect={vi.fn()} />);

    expect(screen.getByText(/audio analysis is temporarily unavailable/i)).toBeInTheDocument();
    expect(
      (document.querySelector('input[type="file"]') as HTMLInputElement).accept
    ).toBe('image/*,video/*');
  });
});
