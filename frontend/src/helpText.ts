/* Every explanation in the window, in one file, so the wording can be read and fixed in one sitting
   rather than hunted through the markup.

   The rule for writing these: plain words a child could follow, and short. A title and one to three
   sentences, no more. Say the thing itself rather than the name of the thing. No "homography", no
   "quantile", no "inference", no asides, no engineering caveats, no dashes.

   Short is not the same as vague. Where a number can mislead, like the alignment score or what "clean"
   promises, the short sentence still has to be the true one: these numbers end up in a survey. */

export type Topic = { title: string; body: string[] }

export const HELP: Record<string, Topic> = {
  camera: {
    title: 'Camera',
    body: [
      'Which camera took these photos.',
      'The app measures them against a flag photo from that same camera. Pick the wrong camera and you still get numbers, but they are wrong.',
    ],
  },
  flag: {
    title: 'Flag photo',
    body: [
      'The photo the app measures against. Someone stood a flag at known spots in front of this camera and took a picture.',
      'Any of them works. If the camera was moved, use one taken after the move.',
    ],
  },
  folder: {
    title: 'Photo folder',
    body: [
      'The photos to measure, usually one memory card copied onto this computer.',
      'Only the photos sitting directly in the folder are measured, not ones in folders inside it.',
    ],
  },
  method: {
    title: 'Distance read at',
    body: [
      'Where on the animal the app measures.',
      'Fast reads the bottom of the box around the animal. Precise traces the animal and reads where its feet touch the ground.',
      'Precise is slower and better when the animal is half hidden.',
    ],
  },
  rerun: {
    title: 'Re-measure photos that already have a number',
    body: [
      'Normally the app skips photos it has already measured, so you can stop and carry on later.',
      'Tick this to measure them again and replace the old numbers.',
      'You do not need it after changing the camera, flag photo or method. The app redoes those by itself.',
    ],
  },
  distance: {
    title: 'The distance',
    body: [
      'How far the animal was from the camera along the ground, in metres.',
      'It is a best guess, not a tape measure.',
    ],
  },
  interval: {
    title: 'The 90% range',
    body: [
      'The app is fairly sure the real distance is between these two numbers.',
      '8.7 m with a range of 6.1 to 12.2 means the deer could be as near as 6 or as far as 12.',
      'A wide range means the app is less sure about this photo.',
    ],
  },
  alignment: {
    title: 'Alignment',
    body: [
      'How well this photo lined up with the flag photo. The app counts matching points on things that do not move, like trees and rocks.',
      'A big number is good. A small or middling one can mean the photo is under the wrong camera, so check it.',
    ],
  },
  needsLook: {
    title: 'Needs a look',
    body: [
      'Photos the app is not confident about and wants a person to glance at.',
      'It says so when the photo lined up poorly, when it was unsure what the animal was, or when it could not read the ground under it.',
      'They are kept, and left out of the exported file unless you ask for them.',
    ],
  },
  clean: {
    title: 'Clean',
    body: [
      'Nothing obvious went wrong. The photo lined up, the animal was clear, and the ground under it could be read.',
      'That is not the same as the number being certain. The 90% range says how sure the app is.',
    ],
  },
  clearPhoto: {
    title: 'Clear this measurement',
    body: [
      'Throws away the number for this one photo. The photo itself is not touched.',
      'Use it when a photo was measured against the wrong camera or flag photo, then measure it again.',
    ],
  },
  clearCamera: {
    title: 'Clear a camera or everything',
    body: [
      'The same, for every measurement of one camera or of this whole computer.',
      'Your photos, cameras and flag photos all stay. There is no undo, so the app asks twice.',
    ],
  },
  sync: {
    title: 'Sync',
    body: [
      'Fetches the flag photos and their markings from FlagLabel.',
      'Do it when a camera is missing from the list. It needs the internet. Measuring does not.',
    ],
  },
  models: {
    title: 'What the app is doing',
    body: [
      'MegaDetector finds the animals, SpeciesNet says what they are, RoMa lines your photo up with the flag photo, and the distance model turns that into metres.',
      'The Precise method also loads SAM 3, which traces the animal.',
      'They load when you press Measure and unload when the run ends, so the graphics card is free in between.',
    ],
  },
}
