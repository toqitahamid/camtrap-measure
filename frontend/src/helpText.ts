/* Every explanation in the window, in one file, so the wording can be read and fixed in one sitting
   rather than hunted through the markup.

   The rule for writing these: plain words, short sentences, and say the thing itself rather than the
   name of the thing. No "homography", no "quantile", no "inference". A biologist opening this app for
   the first time should not have to ask a colleague what a field means.

   Simple is not the same as vague. Where a number can mislead — the interval, the alignment score,
   what "clean" does and does not promise — the simple sentence still has to be the true one, because
   these numbers end up in a survey. */

export type Topic = { title: string; body: string[] }

export const HELP: Record<string, Topic> = {
  camera: {
    title: 'Camera',
    body: [
      'Which camera took the photos you are about to measure.',
      'The app needs to know, because it measures distance by comparing your photos to a picture of a flag standing at a known spot in front of that same camera. A different camera looks at a different piece of forest, so it cannot be used as the comparison.',
      'Pick the camera these photos came from. If you pick the wrong one you will still get numbers, and they will be wrong.',
    ],
  },
  flag: {
    title: 'Flag photo',
    body: [
      'The photo the app measures against.',
      'Someone walked out in front of this camera with a flag, stood in a few known places, and took a picture. Because we know exactly how far away that flag was, the app can work out how far away anything else in the picture is.',
      'A camera can have more than one. They all work; if the camera was bumped or moved, use one taken after the move.',
    ],
  },
  folder: {
    title: 'Photo folder',
    body: [
      'The folder of photos to measure — usually one memory card emptied onto this computer.',
      'The app looks at the photos sitting directly in the folder you choose. It does not go into folders inside it, because those are usually a different camera.',
    ],
  },
  method: {
    title: 'Distance read at',
    body: [
      'Where on the animal the app takes the measurement.',
      'Fast: at the bottom middle of the box drawn around the animal. Good for most photos, and quick.',
      'Precise: the app traces the outline of the animal and measures where its feet touch the ground. Better when the animal is half hidden behind a bush, but several times slower.',
      'Both are honest measurements. The fast one is simply a rougher guess at where the feet are.',
    ],
  },
  rerun: {
    title: 'Re-measure photos that already have a number',
    body: [
      'Normally the app skips photos it has already measured, so you can stop halfway through a card and carry on later without doing the same work twice.',
      'Tick this and it measures everything again, replacing the old numbers.',
      'You do not need it after changing the camera, the flag photo or the method — the app already knows those answers are out of date and redoes them by itself.',
    ],
  },
  distance: {
    title: 'The distance',
    body: [
      'How far the animal was from the camera, along the ground, in metres.',
      'It is a best guess, not a tape measure. That is what the smaller numbers beside it are for.',
    ],
  },
  interval: {
    title: 'The 90% range',
    body: [
      'The app is fairly sure the real distance is somewhere between these two numbers.',
      'If it says 8.7 m and the range is 6.1 to 12.2, it means: the deer is most likely around 8.7 metres away, but do not be surprised if it is as near as 6 or as far as 12.',
      'A wide range is the app telling you it is less certain about this photo. That is useful information, not a fault.',
    ],
  },
  alignment: {
    title: 'Alignment',
    body: [
      'How well this photo lined up with the flag photo.',
      'The app matches things that do not move — tree trunks, rocks, the ground — to work out that the camera is looking at the same scene. The number is how many of those matching points it found.',
      'A big number means the photo and the flag photo really are the same place. A very small one usually means the photo is filed under the wrong camera, or the camera was knocked and is now pointing somewhere else.',
      'Careful: a middling number can still be wrong. Two different patches of forest can look alike enough to match a little. If the number is much smaller than usual for that camera, check the camera is right.',
    ],
  },
  needsLook: {
    title: 'Needs a look',
    body: [
      'The app is not confident about these photos and wants a person to glance at them.',
      'It says so when the photo did not line up well with the flag photo, when it was unsure whether it was really an animal, when it could not tell which animal, or when it could not find the ground under the animal.',
      'They are not thrown away. They are kept, marked, and left out of the exported file unless you ask for them.',
    ],
  },
  clean: {
    title: 'Clean',
    body: [
      'Nothing looked wrong with this photo: it lined up with the flag photo, the app was confident it saw an animal, and it could read the ground underneath it.',
      'It means nothing obvious went wrong — not that the number is certain. The 90% range is where the app tells you how sure it is.',
    ],
  },
  clearPhoto: {
    title: 'Clear this measurement',
    body: [
      'Throws away the number for this one photo, as if it had never been measured.',
      'The photo itself is not deleted. Nothing on your camera card or in your folder is touched — only the measurement the app worked out.',
      'Use it when a photo was measured against the wrong camera or the wrong flag photo. Then measure it again.',
    ],
  },
  clearCamera: {
    title: 'Clear a camera or everything',
    body: [
      'The same thing, for more photos at once: every measurement made for one camera, or every measurement on this computer.',
      'Your photos are safe. So is everything that came from FlagLabel — the cameras, the flag photos and their markings all stay, because you need them to measure again.',
      'There is no undo. The app asks twice before doing it.',
    ],
  },
  sync: {
    title: 'Sync',
    body: [
      'Fetches the flag photos and their markings from FlagLabel, so this computer knows where the flags were standing.',
      'Do it when someone has marked up a new camera, or when a camera is missing from the list. You need the internet for this. Measuring itself does not.',
    ],
  },
  models: {
    title: 'What the app is doing',
    body: [
      'Three steps, for every photo. First it looks for an animal. Then it works out what kind of animal it is. Then it works out how far away it is.',
      'The first run after opening the app takes half a minute longer, because it has to load all that into the graphics card first. After that it is quick.',
    ],
  },
}
