/* Every explanation in the window, in one file, so the wording can be read and fixed in one sitting
   rather than hunted through the markup.

   The rule for writing these: plain words, and short. A title and one to three short sentences, no more.
   The readers are wildlife students and technicians: the ecology terms they report in a thesis (detection
   function, truncation distance, density) stay, each with its plain meaning; software terms do not.
   No em dashes, no asides, no engineering caveats.

   Short is not the same as vague. Where a number can mislead, like the alignment or what "looks fine"
   promises, the short sentence still has to be the true one: these numbers end up in a survey. */

export type Topic = { title: string; body: string[] }

export const HELP: Record<string, Topic> = {
  camera: {
    title: 'Camera',
    body: [
      'The camera that took these photos. Pick the wrong one and the distances are wrong.',
      'A camera marked "not labelled yet" has no flag photo. Label it in FlagLabel, then press Sync.',
    ],
  },
  flag: {
    title: 'Flag photo',
    body: [
      'A photo from this camera with flags at known distances. The app measures against it.',
      'If the camera was moved, use one taken after the move. Flag photos are labelled in FlagLabel.',
    ],
  },
  splitExport: {
    title: 'One file per site or camera',
    body: [
      'Saves one file for each site or camera into a folder you choose, with the filters on this screen.',
      'Nothing is overwritten. A new file gets (2) added to its name.',
    ],
  },
  folder: {
    title: 'Photo folder',
    body: [
      'One camera\'s photos, usually one memory card copied onto this computer.',
      'Or a site folder with one folder per camera inside it. Then every camera is measured in one go.',
    ],
  },
  site: {
    title: 'Site folder',
    body: [
      'Each folder is matched to its camera by name, even when written differently: "mas cam 2" is MAS_CAM02.',
      'The camera name stamped in the photos is checked too, so a folder in the wrong place is caught first.',
      'Change any camera or flag photo with its menu.',
    ],
  },
  byDate: {
    title: 'Flag photo, chosen by date',
    body: [
      'Each photo uses the flag photo from the last visit before it was taken. A card that runs past a service visit switches on its own.',
      'Photos from before the first visit use the setup flag photo.',
    ],
  },
  method: {
    title: 'Distance read at',
    body: [
      'MegaDetector box reads the distance at the bottom of the box around the animal. It is faster.',
      'SAM3 outline traces the animal and reads where its feet touch the ground. It is slower and better when the animal is half hidden.',
    ],
  },
  rerun: {
    title: 'Redo measured photos',
    body: [
      'Photos already measured are normally skipped. Tick this to measure them again.',
      'You do not need it after changing the camera, flag photo or method. The app redoes those itself.',
    ],
  },
  distance: {
    title: 'Distance',
    body: ['How far the animal was from the camera along the ground, in metres. It is a best estimate.'],
  },
  interval: {
    title: '90% range',
    body: [
      'The real distance is very likely between these two numbers.',
      'A wide range means the app is less sure about this photo.',
    ],
  },
  alignment: {
    title: 'Lines up with flag photo',
    body: [
      'Whether this photo matches the flag photo on things that do not move, like trees and rocks.',
      '"Check" can mean the photo is under the wrong camera, or the camera was moved.',
    ],
  },
  clearPhoto: {
    title: 'Clear this measurement',
    body: [
      'Removes the distance for this photo. The photo itself is kept.',
      'Use it when a photo was measured with the wrong camera or flag photo, then measure it again.',
    ],
  },
  clearCamera: {
    title: 'Clear measurements',
    body: [
      'Removes the distances for one camera, or for everything on this computer.',
      'Your photos and flag photos are kept. There is no undo, so the app asks twice.',
    ],
  },
  density: {
    title: 'Density',
    body: [
      'Deer per square kilometre, from how often the cameras saw deer and how far away they were.',
      'Far deer are easy to miss, so the detection function works out how many were missed.',
    ],
  },
  densityRange: {
    title: '90% confidence interval',
    body: [
      'The real density is very likely between these two numbers.',
      'It allows for which deer happened to pass the cameras, and for each distance being an estimate.',
    ],
  },
  detectionFunction: {
    title: 'Detection function',
    body: [
      'How the chance of seeing a deer drops with distance. Bars are the deer counted, the line is the fitted function.',
    ],
  },
  detectionProb: {
    title: 'Detection probability',
    body: ['The share of deer within the truncation distance that the cameras would see.'],
  },
  edr: {
    title: 'Effective detection radius',
    body: ['The distance at which as many deer are missed inside it as are seen beyond it.'],
  },
  reportDetails: {
    title: 'Details for your report',
    body: [
      'The model the app chose and the numbers behind it, to copy into a methods section.',
      'AIC compares the two models. The lower one is used.',
    ],
  },
  snapshot: {
    title: 'Snapshot interval',
    body: [
      'Seconds between the moments the app counts deer. A burst of photos in one moment counts once.',
      'It is found from how often the camera fires while a deer stays. A wrong value changes the density.',
    ],
  },
  truncation: {
    title: 'Truncation distance',
    body: [
      'Deer farther than this are left out, because far ones are hard to see.',
      'Left blank, it is the distance 95% of deer are closer than.',
    ],
  },
  surveyCameras: {
    title: 'Active days and field of view',
    body: [
      'Active days: how long each camera ran, from the flag photo at setup to its last photo.',
      'Field of view: how wide the camera sees, in degrees, from its flag photo. "check" means it is a guess.',
    ],
  },
  rExport: {
    title: 'Export for R Distance',
    body: [
      'A file for the Distance package in R, with the deer, cameras and settings on this screen.',
      'The top of the file says how to load it.',
    ],
  },
  sync: {
    title: 'Sync',
    body: [
      'Brings the flag photos from FlagLabel. Do it after labelling a camera there.',
      'Sync needs the internet. Measuring does not.',
    ],
  },
  models: {
    title: 'What the app does',
    body: [
      'It finds each animal (MegaDetector), names it (SpeciesNet), lines the photo up with the flag photo (RoMa), and turns that into metres.',
      'The SAM3 outline method also traces the animal. Everything loads when you press Measure.',
    ],
  },
}
