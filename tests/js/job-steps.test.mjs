// The import's loading screen: which steps a job goes through, which are
// done (from stage_timings, as app/pipeline/runner.py writes them), which
// runs and how far, and the server's notes worth saying.
//
// Run:  node tests/js/job-steps.test.mjs

import { jobSteps, stageNote, fmtSeconds } from '../../static/js/jobSteps.js';

let passed = 0;
let failed = 0;

function check(name, condition, detail = '') {
  if (condition) {
    passed++;
    console.log(`PASS  ${name}`);
  } else {
    failed++;
    console.log(`FAIL  ${name}${detail ? `  -- ${detail}` : ''}`);
  }
}

const ids = (r) => r.steps.map((s) => s.id).join(',');
const states = (r) => r.steps.map((s) => s.state).join(',');

// A link, queued.
let r = jobSteps({ status: 'queued', source_url: 'https://youtu.be/x', separator: 'demucs' });
check('a link: download, analysis, separation, mix, beats, lyrics', ids(r) === 'download,analyze,separate,mix,beats,lyrics', ids(r));
check('queued: nothing runs yet', r.queued && r.current === null && r.overall === 0, JSON.stringify(r));

// Downloading, 40 %.
r = jobSteps({ status: 'downloading', progress: 0.4, source_url: 'https://youtu.be/x' });
check('downloading: the download runs with its own %', r.current === 'download' && r.steps[0].fraction === 0.4);
check('the whole moves with it', r.overall > 0 && r.overall < 0.12, String(r.overall));

// Separating 50 %, after download and analysis.
r = jobSteps({ status: 'separating', progress: 0.5, source_url: 'https://youtu.be/x', stage_timings: { download: 12.3, analyze: 2.1 } });
check('separating: two done, separation now', states(r) === 'done,done,now,next,next,next', states(r));
check('a done step keeps its time', r.steps[0].seconds === 12.3);
check('separation reports its %', r.steps[2].fraction === 0.5);
const half = r.overall;
check('half the separation is past a quarter of the whole', half > 0.3 && half < 0.6, String(half));

// After separation: the progress left over from it is not the mix's.
r = jobSteps({ status: 'separating', progress: 1, stage: 'Mixing tracks...', source_url: 'https://youtu.be/x', stage_timings: { download: 1, analyze: 1, separate: 30 } });
check('mixing: no % of its own (the separator\'s 100 % is not its)', r.current === 'mix' && r.steps[3].fraction === null);
const early = jobSteps({ status: 'separating', progress: 1, source_url: 'https://youtu.be/x', stage_timings: { download: 1, analyze: 1, separate: 30 } }, 0).overall;
const later = jobSteps({ status: 'separating', progress: 1, source_url: 'https://youtu.be/x', stage_timings: { download: 1, analyze: 1, separate: 30 } }, 30).overall;
check('a step with no % creeps on with time, never to its end', later > early && later < (12 + 6 + 55 + 8 * 0.9) / 94, `${early} ${later}`);

// Lyrics: done only once timed (the last of its four timings).
r = jobSteps({ status: 'separating', source_url: 'https://youtu.be/x', stage_timings: { download: 1, analyze: 1, separate: 1, post: 1, beatgrid: 1, sections: 0, identify_wait: 0.2, lyrics_wait: 0.1 } });
check('lyrics: running until retimed', r.current === 'lyrics', r.current);
r = jobSteps({ status: 'separating', source_url: 'https://youtu.be/x', stage_timings: { download: 1, analyze: 1, separate: 1, post: 1, beatgrid: 1, sections: 0, identify_wait: 0.2, lyrics_wait: 0.1, transcribe: 3, retime: 1 } });
check('lyrics done: its time is the four together', r.steps[5].state === 'done' && Math.abs(r.steps[5].seconds - 4.3) < 1e-9, JSON.stringify(r.steps[5]));

// An upload, a solo piano, structure asked for.
r = jobSteps({ status: 'analyzing', source_url: 'local:clip', separator: 'none', auto_sections: true, stage_timings: { prepare: 0.4 } });
check('upload + solo piano + structure: prepare, solo, sections, no lyrics', ids(r) === 'prepare,analyze,solo,mix,beats,sections', ids(r));
check('analysing now', r.current === 'analyze');

// Done.
r = jobSteps({ status: 'done', source_url: 'https://youtu.be/x' });
check('done: every step done, the whole full', r.finished && r.overall === 1 && r.steps.every((s) => s.state === 'done'));

// The server's notes.
check('network retry said', stageNote('Network error — retrying (2/3)...')?.vars?.n === '2');
check('GPU fallback said', stageNote('GPU failed — retrying on CPU (slower)...')?.key === 'jobProgress.note.gpuFailed');
check('a plain stage says nothing more', stageNote('Separating 42%') === null && stageNote('') === null);

check('seconds', fmtSeconds(12.4) === '12 s' && fmtSeconds(65) === '1:05' && fmtSeconds(3723) === '1:02:03');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
