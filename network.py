import os

import tensorflow as tf

import Input

FLAGS = tf.app.flags.FLAGS

tf.app.flags.DEFINE_integer('batch_input_size', 128, """Number of images to process in a batch.""")
tf.app.flags.DEFINE_string('data_input_dir', '/home/khc/MLProject', """Path to the FER2013 data directory.""")

IMAGE_SIZE = Input.IMAGE_SIZE
NUM_CLASSES = Input.NUM_CLASSES
NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN = Input.NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN
NUM_EXAMPLES_PER_EPOCH_FOR_EVAL = Input.NUM_EXAMPLES_PER_EPOCH_FOR_EVAL


MOVING_AVERAGE_DECAY = 0.9999     # The decay to use for the moving average
NUM_EPOCHS_PER_DECAY = 350.0      # Epochs after which learning rate decays.
LEARNING_RATE_DECAY_FACTOR = 0.1  # Learning rate decay factor.
INITIAL_LEARNING_RATE = 0.1       # Initial learning rate.


def _variable_with_weight_decay(name, shape, stddev, wd):
  var = tf.get_variable(name, shape,
                         initializer=tf.truncated_normal_initializer(stddev=stddev))
  if wd:
    weight_decay = tf.mul(tf.nn.l2_loss(var), wd, name='weight_loss')
    tf.add_to_collection('losses', weight_decay)
  return var


def distorted_inputs():
  if not FLAGS.data_input_dir:
    raise ValueError('Please supply a data_input_dir')
  data_input_dir = os.path.join(FLAGS.data_input_dir, 'fer_data')
  return Input.distorted_inputs(data_dir=data_input_dir,
                                        batch_size=FLAGS.batch_input_size)


def inputs(eval_data):
  if not FLAGS.data_input_dir:
    raise ValueError('Please supply a data_input_dir')
  data_input_dir = os.path.join(FLAGS.data_input_dir, 'fer_data')
  return Input.inputs(eval_data=eval_data, data_dir=data_input_dir,
                              batch_size=FLAGS.batch_input_size)

def inference(images):
  # conv0 layer takes 32x32 images as input and outputs 24x24 feature maps.
  with tf.variable_scope('conv0') as scope:
    kernel = _variable_with_weight_decay('weights', shape=[9, 9, 1, 64], stddev=1e-4, wd=0.0)

    conv = tf.nn.conv2d(images, kernel, [1, 1, 1, 1], padding='VALID')
    biases = tf.get_variable('biases', [64], initializer=tf.constant_initializer(0.0))
    bias = tf.nn.bias_add(conv, biases)
    conv0 = tf.nn.relu(bias, name=scope.name)

  pool0 = tf.nn.max_pool(conv0, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool0')

  norm0 = tf.nn.lrn(pool0, 4, bias=1.0, alpha=0.001 / 9.0, beta=0.75, name='norm0')

  with tf.variable_scope('conv1') as scope:
    kernel = _variable_with_weight_decay('weights', shape=[5, 5, 64, 128], stddev=1e-4, wd=0.0)

    conv = tf.nn.conv2d(norm0, kernel, [1, 1, 1, 1], padding='SAME')
    biases = tf.get_variable('biases', [128], initializer=tf.constant_initializer(0.1))
    bias = tf.nn.bias_add(conv, biases)
    conv1 = tf.nn.relu(bias, name=scope.name)

  norm1 = tf.nn.lrn(conv1, 4, bias=1.0, alpha=0.001 / 9.0, beta=0.75, name='norm1')

  pool1 = tf.nn.max_pool(norm1, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool1')

  with tf.variable_scope('local3') as scope:
    dim = 1
    for d in pool1.get_shape()[1:].as_list():
      dim *= d
    reshape = tf.reshape(pool1, [FLAGS.batch_input_size, dim])

    weights = _variable_with_weight_decay('weights', shape=[dim, 384],
                                          stddev=0.04, wd=0.004)
    biases = tf.get_variable('biases', [384], initializer=tf.constant_initializer(0.1))
    local3 = tf.nn.relu(tf.matmul(reshape, weights) + biases, name=scope.name)

  with tf.variable_scope('local4') as scope:
    weights = _variable_with_weight_decay('weights', shape=[384, 192],
                                          stddev=0.04, wd=0.004)
    biases = tf.get_variable('biases', [192], initializer=tf.constant_initializer(0.1))
    local4 = tf.nn.relu(tf.matmul(local3, weights) + biases, name=scope.name)

  with tf.variable_scope('softmax_linear') as scope:
    weights = _variable_with_weight_decay('weights', [192, NUM_CLASSES],
                                          stddev=1/192.0, wd=0.0)
    biases = tf.get_variable('biases', [NUM_CLASSES],
                              initializer=tf.constant_initializer(0.0))
    softmax_linear = tf.add(tf.matmul(local4, weights), biases, name=scope.name)

  return softmax_linear


def loss(logits, labels):
  labels = tf.cast(labels, tf.int64)
  cross_entropy = tf.nn.sparse_softmax_cross_entropy_with_logits(
      logits, labels, name='cross_entropy_per_example')
  cross_entropy_mean = tf.reduce_mean(cross_entropy, name='cross_entropy')
  tf.add_to_collection('losses', cross_entropy_mean)

  return tf.add_n(tf.get_collection('losses'), name='total_loss')


def _add_loss_summaries(total_loss):
  loss_averages = tf.train.ExponentialMovingAverage(0.9, name='avg')
  losses = tf.get_collection('losses')
  loss_averages_op = loss_averages.apply(losses + [total_loss])
  
  tf.scalar_summary('total_loss(raw)',total_loss)

  return loss_averages_op


def train(total_loss, global_step):
  num_batches_per_epoch = NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN / FLAGS.batch_input_size
  decay_steps = int(num_batches_per_epoch * NUM_EPOCHS_PER_DECAY)

  lr = tf.train.exponential_decay(INITIAL_LEARNING_RATE,
                                  global_step,
                                  decay_steps,
                                  LEARNING_RATE_DECAY_FACTOR,
                                  staircase=True)
  tf.scalar_summary('learning_rate', lr)

  loss_averages_op = _add_loss_summaries(total_loss)

  with tf.control_dependencies([loss_averages_op]):
    opt = tf.train.GradientDescentOptimizer(lr)
    grads = opt.compute_gradients(total_loss)

  apply_gradient_op = opt.apply_gradients(grads, global_step=global_step)

  variable_averages = tf.train.ExponentialMovingAverage(
      MOVING_AVERAGE_DECAY, global_step)
  variables_averages_op = variable_averages.apply(tf.trainable_variables())

  with tf.control_dependencies([apply_gradient_op, variables_averages_op]):
    train_op = tf.no_op(name='train')

  return train_op
