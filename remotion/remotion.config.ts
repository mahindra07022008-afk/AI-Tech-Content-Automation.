import {Config} from '@remotion/cli/config';

// Rendering defaults for the premium pipeline. The Python orchestrator passes the browser
// executable (pre-installed Chrome headless shell) and concurrency explicitly.
Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(92);
Config.setCodec('h264');
Config.setCrf(18);
Config.setPixelFormat('yuv420p');
Config.setChromiumOpenGlRenderer('swangle');
