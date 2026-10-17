/*
 * Video orientation constant used by MovieAgent for decoded texture frames.
 *
 * Editing notes: The matrix flips vertical texture coordinates; changing it affects all
 * transformed movie frames and needs native playback verification.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

/** Android video texture coordinates compensate for top-first decoded rows. */
public class MovieOrientation {
    public static final float[] VERTICAL_FLIP = {1, 0, 0, 0, 0, -1, 0, 0,
                                                 0, 0, 1, 0, 0, 1,  0, 1};
}
