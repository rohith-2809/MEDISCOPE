// =============================
// MAIN SERVER (CLEAN DEPLOYMENT VERSION)
// =============================
const FormData = require("form-data");
const express = require("express");
const axios = require("axios");
const mongoose = require("mongoose");
const dotenv = require("dotenv");
const cors = require("cors");
const { Server } = require("socket.io");
const http = require("http");
const bcrypt = require("bcryptjs");
const jwt = require("jsonwebtoken");
const multer = require("multer");
const path = require("path");
const fs = require("fs");

dotenv.config();

const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: "*" } });

// -----------------------------
// MIDDLEWARE
// -----------------------------
app.use(
  cors({
    origin: [
      "https://mediscope-frontend-lxwd.onrender.com",
      "http://localhost:5173"
    ],
    methods: ["GET", "POST", "PUT", "DELETE"],
    credentials: true,
  })
);
app.use(express.json());
app.use("/uploads", express.static(path.join(__dirname, "uploads")));

// -----------------------------
// DATABASE CONNECTION
// -----------------------------
mongoose
  .connect(process.env.MONGO_URI)
  .then(() => console.log("✅ MongoDB Connected"))
  .catch((err) => console.error("❌ MongoDB Connection Error:", err.message));

// -----------------------------
// SCHEMAS
// -----------------------------
const userSchema = new mongoose.Schema({
  name: String,
  email: { type: String, unique: true },
  password: String,
});

const historySchema = new mongoose.Schema({
  userId: { type: mongoose.Schema.Types.ObjectId, ref: "User" },
  requestId: String,
  type: String,
  fileName: String,
  rawOutput: Object,
  interpretedOutput: Object,
  status: String,
  createdAt: { type: Date, default: Date.now },
});

const User = mongoose.model("User", userSchema);
const History = mongoose.model("History", historySchema);

// -----------------------------
// AUTH HELPERS
// -----------------------------
const JWT_SECRET = process.env.JWT_SECRET || "supersecretjwtkey";

const generateToken = (user) =>
  jwt.sign({ id: user._id, name: user.name }, JWT_SECRET, { expiresIn: "1d" });

const authMiddleware = (req, res, next) => {
  const token = req.headers.authorization?.split(" ")[1];
  if (!token) return res.status(401).json({ error: "Unauthorized" });
  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    req.user = decoded;
    next();
  } catch {
    res.status(401).json({ error: "Invalid token" });
  }
};

// -----------------------------
// FILE UPLOAD
// -----------------------------
const UPLOAD_DIR = path.resolve(__dirname, "uploads");
if (!fs.existsSync(UPLOAD_DIR)) fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const storage = multer.diskStorage({
  destination: (_, __, cb) => cb(null, UPLOAD_DIR),
  filename: (_, file, cb) =>
    cb(null, `${Date.now()}_${file.originalname.replace(/\s+/g, "_")}`),
});
const upload = multer({ storage });

// -----------------------------
// SAFE POST UTILITY
// -----------------------------
async function safePost(url, data, headers = {}) {
  const res = await axios.post(url, data, { headers, timeout: 60000 });
  return res.data;
}

// -----------------------------
// AUTH ROUTES
// -----------------------------
app.post("/signup", async (req, res) => {
  const { name, email, password } = req.body;
  if (!name || !email || !password)
    return res.status(400).json({ error: "All fields are required" });

  try {
    const existing = await User.findOne({ email });
    if (existing) return res.status(409).json({ error: "User already exists" });

    const hashed = await bcrypt.hash(password, 10);
    const user = await User.create({ name, email, password: hashed });
    const token = generateToken(user);
    res.json({ message: "Signup successful", token, user: { id: user._id, name, email } });
  } catch {
    res.status(500).json({ error: "Signup failed" });
  }
});

app.post("/login", async (req, res) => {
  const { email, password } = req.body;
  if (!email || !password)
    return res.status(400).json({ error: "Email and password required" });

  try {
    const user = await User.findOne({ email });
    if (!user) return res.status(404).json({ error: "User not found" });

    const valid = await bcrypt.compare(password, user.password);
    if (!valid) return res.status(401).json({ error: "Invalid credentials" });

    const token = generateToken(user);
    res.json({ message: "Login successful", token, user: { id: user._id, name: user.name, email } });
  } catch {
    res.status(500).json({ error: "Login failed" });
  }
});

app.post("/process", authMiddleware, upload.single("file"), async (req, res) => {
  console.log("🔥 [PROCESS] Endpoint hit!");
  console.log("👤 Authenticated user:", req.user);
  console.log("📥 Headers:", req.headers);
  console.log("📥 Body:", req.body);
  console.log("📎 Uploaded file info:", req.file);

  if (!req.file) {
    console.log("❌ No file uploaded");
    return res.status(400).json({ error: "No file uploaded" });
  }

  const { type, language } = req.body;
  if (!["xray", "lab", "labreport"].includes(type)) {
    console.log("❌ Invalid type:", type);
    return res.status(400).json({ error: "Invalid type" });
  }

  const requestId = `REQ-${Date.now()}`;
  const userId = req.user.id;

  console.log(`🟢 Processing request ${requestId} for user ${userId}`);
  io.emit("status", { userId, requestId, step: "started" });

  try {
    let microResponse = null;

    // ======================================
    // 🧠 X-RAY HANDLER
    // ======================================
    if (type === "xray") {
      console.log("🧠 [X-RAY] Preparing to call microservice...");

      const filePath = req.file.path;
      console.log("📂 Reading file from:", filePath);

      const fileBuffer = fs.readFileSync(filePath);
      const base64Image = fileBuffer.toString("base64");
      console.log(
        "🖼️ Converted image to Base64 (first 50 chars):",
        base64Image.slice(0, 50) + "..."
      );

      const payload = {
        payload: {
          image_base64: base64Image,
          body_part: "X-ray",
          age: 30,
          weight: 70,
          symptoms: "unknown",
        },
      };

      // Hardcoded X-ray URL
      const XRAY_URL = "https://mediscope-1.onrender.com";
      console.log("🌐 Calling X-ray microservice at:", `${XRAY_URL}/predict`);

      const response = await axios.post(`${XRAY_URL}/predict`, payload, {
        headers: { "Content-Type": "application/json" },
      });

      microResponse = response.data;
      console.log("✅ [X-RAY] Microservice Response:", microResponse);
    }

    // ======================================
    // 🧪 LAB REPORT HANDLER
    // ======================================
    else if (type === "labreport" || type === "lab") {
      console.log("🧪 [LAB] Preparing to call Lab microservice...");

      // Hardcoded Lab URL
      const LAB_URL = "https://mediscope-lab.onrender.com";
      console.log("🌍 Target URL:", `${LAB_URL}/parse`);
      console.log("📄 Sending file path:", req.file.path);

      try {
        // Send actual file stream
        const formData = new FormData();
        formData.append("file", fs.createReadStream(req.file.path));

        console.log("📤 [LAB] Sending file to microservice...");
        const labResponse = await axios.post(`${LAB_URL}/parse`, formData, {
          headers: formData.getHeaders(),
        });

        microResponse = labResponse.data;
        console.log("✅ [LAB] Microservice Response:", microResponse);
      } catch (err) {
        console.error("❌ [LAB] Microservice Error:", err.message);
        return res
          .status(500)
          .json({ error: "Lab microservice failed", details: err.message });
      }
    }

    // ======================================
    // 🎯 EMIT MICROSERVICE RESULT
    // ======================================
    io.emit("status", {
      userId,
      requestId,
      step: "microservice_complete",
      data: microResponse,
    });

    // ======================================
    // 🧠 INTERPRETER CALL
    // ======================================
    console.log("🧠 [INTERPRETER] Sending data for interpretation...");

    // Hardcoded Interpreter URL
    const INTERPRETER_URL = "https://mediscope-interpreter.onrender.com";

    const formData2 = new FormData();
    formData2.append("username", req.user.name || "User");
    formData2.append("language", language || "english");
    formData2.append("predictions", JSON.stringify(microResponse));

    const interpreted = await safePost(
      `${INTERPRETER_URL}/interpret`,
      formData2,
      formData2.getHeaders()
    );

    console.log("✅ [INTERPRETER] Response:", interpreted);

    // ======================================
    // 💾 SAVE HISTORY
    // ======================================
    await History.create({
      userId,
      requestId,
      type,
      fileName: req.file.filename,
      rawOutput: microResponse,
      interpretedOutput: interpreted,
      status: "completed",
    });

    console.log("💾 History saved successfully!");
    io.emit("completed", { userId, requestId, interpreted });

    res.json({ success: true, requestId, interpreted });
  } catch (err) {
    console.error("❌ [PROCESS ERROR]:", err.message);
    io.emit("failed", { userId, requestId, error: err.message });
    res
      .status(500)
      .json({ error: "Processing failed", message: err.message });
  } finally {
    // ======================================
    // 🧹 CLEANUP
    // ======================================
    if (req.file && fs.existsSync(req.file.path)) {
      fs.unlinkSync(req.file.path);
      console.log("🗑️ Cleaned up uploaded file:", req.file.path);
    }
    console.log("🏁 [PROCESS] Completed request lifecycle.");
  }
});

// -----------------------------
// HISTORY
// -----------------------------
app.get("/history", authMiddleware, async (req, res) => {
  const history = await History.find({ userId: req.user.id }).sort({ createdAt: -1 });
  res.json(history);
});

// -----------------------------
// SOCKET.IO
// -----------------------------
io.on("connection", (socket) => {
  console.log("🔌 Client connected:", socket.id);
  socket.on("disconnect", () => console.log("❌ Client disconnected:", socket.id));
});

// -----------------------------
// START SERVER
// -----------------------------
const PORT = process.env.PORT || 4000;
server.listen(PORT, () => console.log(`🚀 Server running on port ${PORT}`));
