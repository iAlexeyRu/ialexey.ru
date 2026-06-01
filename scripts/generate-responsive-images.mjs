import fs from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';

const root = process.cwd();
const habrDir = path.join(root, 'public', 'habr-images');
const widths = [360, 640, 960];

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function generateHabrImages() {
  if (!(await exists(habrDir))) {
    return;
  }

  const files = await fs.readdir(habrDir);
  for (const file of files) {
    if (!/\.(jpe?g|png)$/i.test(file)) {
      continue;
    }

    const inputPath = path.join(habrDir, file);
    const parsed = path.parse(file);
    const image = sharp(inputPath);
    const metadata = await image.metadata();
    const sourceWidth = metadata.width || 0;

    for (const width of widths) {
      if (sourceWidth && width > sourceWidth) {
        continue;
      }
      const outputPath = path.join(habrDir, `${parsed.name}-${width}.webp`);
      await sharp(inputPath)
        .resize({ width, withoutEnlargement: true })
        .webp({ quality: 74, effort: 6 })
        .toFile(outputPath);
    }
  }
}

async function generateAvatar() {
  const inputPath = path.join(root, 'public', 'avatar-small.png');
  if (!(await exists(inputPath))) {
    return;
  }

  await sharp(inputPath)
    .resize({ width: 72, height: 72, fit: 'cover' })
    .webp({ quality: 76, effort: 6 })
    .toFile(path.join(root, 'public', 'avatar-small.webp'));
}

await generateHabrImages();
await generateAvatar();
