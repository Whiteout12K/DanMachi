/*
 * Java startup agent. Transform only named runtime classes in memory to install video
 * and input compatibility helpers.
 *
 * Editing notes: The ordered class/method guards are deliberate. Keep exact JVM
 * descriptors and stack-map instructions compatible with the retained runtime; original
 * JAR inputs are not rewritten.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

import java.lang.instrument.*;
import java.security.ProtectionDomain;
import java.util.*;
import java.util.jar.JarFile;
import jdk.internal.org.objectweb.asm.*;
import jdk.internal.org.objectweb.asm.tree.*;
public class MovieAgent {
    public static void premain(String arg, Instrumentation inst) throws Exception {
        System.setProperty("danmachi.input.geometry", java.nio.file.Path.of(arg)
                                                          .toAbsolutePath()
                                                          .getParent()
                                                          .getParent()
                                                          .resolve("window_fit.dylib")
                                                          .toString());
        inst.appendToBootstrapClassLoaderSearch(new JarFile(arg));
        inst.redefineModule(Object.class.getModule(), Set.of(),
                            Map.of("jdk.internal.org.objectweb.asm",
                                   Set.of(MovieAgent.class.getModule()),
                                   "jdk.internal.org.objectweb.asm.tree",
                                   Set.of(MovieAgent.class.getModule())),
                            Map.of(), Set.of(), Map.of());
        inst.addTransformer(new ClassFileTransformer() {
            public byte[] transform(ClassLoader l, String n, Class<?> c,
                                    ProtectionDomain p, byte[] b) {
                if (!n.equals("android/media/MediaCodec") &&
                    !n.equals("org/cocos2dx/lib/Cocos2dxGLSurfaceView") &&
                    !n.equals("android/widget/TextView") &&
                    !n.equals("android/graphics/SurfaceTexture") &&
                    !n.equals("com/macapk/loader/KeyBindProfiles"))
                    return null;
                try {
                    ClassNode cn = new ClassNode();
                    new ClassReader(b).accept(cn, 0);
                    for (MethodNode m : cn.methods) {
                        // Install movement bindings, but yield to ordinary keyboard input while typing.
                        if (n.equals("com/macapk/loader/KeyBindProfiles")) {
                            if (m.name.equals("autoSelectForPackage") &&
                                m.desc.equals("(Ljava/lang/String;)V")) {
                                LabelNode normal = new LabelNode();
                                InsnList a = new InsnList();
                                a.add(new LdcInsnNode(Type.getObjectType(n)));
                                a.add(new VarInsnNode(Opcodes.ALOAD, 0));
                                a.add(new MethodInsnNode(
                                    Opcodes.INVOKESTATIC, "AisWarKeyboard", "install",
                                    "(Ljava/lang/Class;Ljava/lang/String;)Z", false));
                                a.add(new JumpInsnNode(Opcodes.IFEQ, normal));
                                a.add(new InsnNode(Opcodes.RETURN));
                                a.add(normal);
                                a.add(new FrameNode(Opcodes.F_SAME, 0, null, 0, null));
                                m.instructions.insert(a);
                            }
                            if (m.name.equals("active") &&
                                m.desc.equals(
                                    "()Lcom/macapk/loader/KeyBindProfiles$Profile;")) {
                                LabelNode normal = new LabelNode();
                                InsnList a = new InsnList();
                                a.add(new LdcInsnNode(Type.getObjectType(n)));
                                a.add(new MethodInsnNode(
                                    Opcodes.INVOKESTATIC, "AisWarKeyboard", "typing",
                                    "(Ljava/lang/Class;)Z", false));
                                a.add(new JumpInsnNode(Opcodes.IFEQ, normal));
                                a.add(new InsnNode(Opcodes.ACONST_NULL));
                                a.add(new InsnNode(Opcodes.ARETURN));
                                a.add(normal);
                                a.add(new FrameNode(Opcodes.F_SAME, 0, null, 0, null));
                                m.instructions.insert(a);
                            }
                            continue;
                        }
                        // Use the vertical texture transform on decoded video frames.
                        if (n.equals("android/graphics/SurfaceTexture")) {
                            if (m.name.equals("macapkQueueDecodedFrame"))
                                for (AbstractInsnNode i : m.instructions.toArray())
                                    if (i.getOpcode() == Opcodes.ACONST_NULL) {
                                        m.instructions.set(
                                            i,
                                            new FieldInsnNode(Opcodes.GETSTATIC,
                                                              "MovieOrientation",
                                                              "VERTICAL_FLIP", "[F"));
                                        break;
                                    }
                            continue;
                        }
                        // Preserve native editing and add the Cocos watcher notification bridge.
                        if (n.equals("android/widget/TextView")) {
                            if (m.name.equals("onKeyDown"))
                                for (AbstractInsnNode i : m.instructions.toArray())
                                    if (i instanceof MethodInsnNode &&
                                        ((MethodInsnNode)i)
                                            .owner.equals(
                                                "android/text/method/KeyListener") &&
                                        ((MethodInsnNode)i).name.equals("onKeyDown"))
                                        m.instructions.set(
                                            i,
                                            new MethodInsnNode(
                                                Opcodes.INVOKESTATIC, "KeyboardSupport",
                                                "keyListener",
                                                "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;ILjava/lang/Object;)Z",
                                                false));
                            continue;
                        }
                        // Replace a nullable focus-token lookup with the safe helper.
                        if (n.equals("org/cocos2dx/lib/Cocos2dxGLSurfaceView")) {
                            for (AbstractInsnNode i : m.instructions.toArray())
                                if (i instanceof MethodInsnNode &&
                                    ((MethodInsnNode)i).name.equals("getWindowToken") &&
                                    ((MethodInsnNode)i)
                                        .desc.equals("()Landroid/os/IBinder;")) {
                                    InsnList a = new InsnList();
                                    a.add(new VarInsnNode(Opcodes.ALOAD, 0));
                                    a.add(new MethodInsnNode(
                                        Opcodes.INVOKESTATIC, "KeyboardSupport",
                                        "windowToken",
                                        "(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;",
                                        false));
                                    a.add(new TypeInsnNode(Opcodes.CHECKCAST,
                                                           "android/os/IBinder"));
                                    m.instructions.insertBefore(i, a);
                                    m.instructions.remove(i);
                                }
                            continue;
                        }
                        // Permit deferred decoder startup when H.264 configuration arrives in packets.
                        if (m.name.equals("start")) {
                            for (AbstractInsnNode i : m.instructions.toArray())
                                if (i instanceof FieldInsnNode &&
                                    ((FieldInsnNode)i).name.equals("mVidDec") &&
                                    i.getOpcode() == Opcodes.GETFIELD) {
                                    AbstractInsnNode j = i;
                                    while (j != null && !(j instanceof JumpInsnNode))
                                        j = j.getNext();
                                    if (j instanceof JumpInsnNode &&
                                        j.getOpcode() == Opcodes.IFNE) {
                                        InsnList a = new InsnList();
                                        a.add(new VarInsnNode(Opcodes.ALOAD, 0));
                                        a.add(new MethodInsnNode(
                                            Opcodes.INVOKESTATIC, "MovieDeferred",
                                            "defer", "(Ljava/lang/Object;)Z", false));
                                        a.add(new JumpInsnNode(
                                            Opcodes.IFNE, ((JumpInsnNode)j).label));
                                        m.instructions.insert(j, a);
                                        break;
                                    }
                                }
                        }
                        // Inspect queued input for decoder parameter sets before native packet handling.
                        if (m.name.equals("queueInputBuffer") &&
                            m.desc.equals("(IIIJI)V")) {
                            InsnList a = new InsnList();
                            a.add(new VarInsnNode(Opcodes.ALOAD, 0));
                            a.add(new VarInsnNode(Opcodes.ILOAD, 1));
                            a.add(new VarInsnNode(Opcodes.ILOAD, 2));
                            a.add(new VarInsnNode(Opcodes.ILOAD, 3));
                            a.add(new VarInsnNode(Opcodes.ILOAD, 6));
                            a.add(new MethodInsnNode(
                                Opcodes.INVOKESTATIC, "MovieDeferred", "input",
                                "(Ljava/lang/Object;IIII)V", false));
                            m.instructions.insert(a);
                        }
                    }
                    ClassWriter w = new ClassWriter(ClassWriter.COMPUTE_MAXS);
                    cn.accept(w);
                    System.err.println(
                        n.equals("com/macapk/loader/KeyBindProfiles")
                            ? "[ais-war] in-memory keyboard profile support installed"
                        : n.equals("android/media/MediaCodec")
                            ? "[movie] deferred H264 setup installed"
                            : "[keyboard] Cocos null-focus correction installed");
                    return w.toByteArray();
                } catch (Throwable e) {
                    e.printStackTrace();
                    return null;
                }
            }
        });
    }
}
